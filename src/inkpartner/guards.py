"""Hard rules for anything that writes to the tablet. Checked inside the write calls themselves, so no
caller - this agent, a future one, a hurried test script - can skip them.

Every rule comes from something that went wrong (Codex grill session and the device on 2026-10-23):

  R-RESTART   A restart logs the student out. Only if explicitly allowed, after 30 min without a change
              on any page AND without any real pen activity, at most once per hour.
  R-PEN-NEAR  Pen events only while the real pen has been out of range for a few seconds. With the real
              pen hovering, injected touch-downs were swallowed and the strokes merged into one line.
  R-OPEN      Pen events only into the page that is open on the screen - otherwise they land somewhere
              else (another page, the library menu).
  R-VIEWPORT  Pen events only in a viewport the calibration holds for (unzoomed). Zoomed out, a note was
              drawn as a large shape across the student's own calculation.
  R-FOREIGN   After pen events: new strokes in the student's layer that are neither the expected agent
              ink nor written while the real pen was active are the agent's garbage. -> STOP.
  R-PREFIX    A page file may only grow: the student's original bytes stay a byte-identical prefix.
  R-RATE      At most a few pen deliveries per minute.

A violation of R-FOREIGN or R-PREFIX trips the kill switch: a STOP file that blocks every write until a
human removes it. The other rules simply refuse the single write.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from . import verify


class GuardError(RuntimeError):
    """This write is refused."""


class Stopped(GuardError):
    """The kill switch is set; no write at all until a human clears it."""


@dataclass
class Limits:
    restart_quiet_s: float = 1800.0
    restart_gap_s: float = 3600.0
    pen_away_s: float = 3.0
    pen_per_minute: int = 4
    foreign_tolerance: float = 10.0


@dataclass
class GuardState:
    last_restart: float = -1e18
    pen_times: list = field(default_factory=list)


class Guard:
    def __init__(self, stop_file: str | Path, limits: Limits | None = None, clock=time.time, log=print):
        self.stop_file = Path(stop_file)
        self.limits = limits or Limits()
        self.clock = clock
        self.log = log
        self.state = GuardState()

    # ------------------------------------------------------------- kill switch
    def check_not_stopped(self):
        if self.stop_file.exists():
            raise Stopped(f"writes stopped: {self.stop_file.read_text().strip()} "
                          f"(remove {self.stop_file} after checking the tablet)")

    def trip(self, rule: str, detail: str):
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        self.stop_file.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {rule}: {detail}\n")
        self.log(f"KILL SWITCH {rule}: {detail}")
        raise Stopped(f"{rule}: {detail}")

    # -------------------------------------------------------------- restart
    def before_restart(self, *, allowed: bool, quiet_s: float, pen_idle_s: float | None):
        self.check_not_stopped()
        L, now = self.limits, self.clock()
        if not allowed:
            raise GuardError("R-RESTART: restart not allowed (it logs the student out)")
        if quiet_s < L.restart_quiet_s:
            raise GuardError(f"R-RESTART: pages changed {quiet_s:.0f}s ago (< {L.restart_quiet_s:.0f}s)")
        if pen_idle_s is None or pen_idle_s < L.restart_quiet_s:
            raise GuardError("R-RESTART: real pen activity unknown or too recent")
        if now - self.state.last_restart < L.restart_gap_s:
            raise GuardError("R-RESTART: already restarted within the last hour")
        self.state.last_restart = now

    # ------------------------------------------------------------------ pen
    def before_pen(self, *, target_doc: str, target_page: str, open_page: tuple[str, str] | None,
                   pen_idle_s: float | None, viewport_ok: bool):
        self.check_not_stopped()
        L, now = self.limits, self.clock()
        if open_page != (target_doc, target_page):
            raise GuardError(f"R-OPEN: open page is {open_page}, target is {(target_doc, target_page)}")
        if pen_idle_s is None or pen_idle_s < L.pen_away_s:
            raise GuardError("R-PEN-NEAR: the real pen is (or may be) in range")
        if not viewport_ok:
            raise GuardError("R-VIEWPORT: viewport not known to match the calibration")
        self.state.pen_times = [t for t in self.state.pen_times if now - t < 60]
        if len(self.state.pen_times) >= L.pen_per_minute:
            raise GuardError("R-RATE: too many pen deliveries in the last minute")
        self.state.pen_times.append(now)

    def after_pen(self, *, before: list[dict], after: list[dict], expected: list[dict],
                  real_pen_during: bool):
        """New student-layer strokes must be ours (expected) or the student's own (real pen active)."""
        seen = {tuple(map(tuple, s["points"])) for s in before}
        new = [s for s in after if s.get("author") == "user" and tuple(map(tuple, s["points"])) not in seen]
        cand = [{**e, "action": "x"} for e in expected]
        foreign = [s for s in new
                   if verify.coverage({"points": s["points"]}, cand, tol=self.limits.foreign_tolerance) < 0.8]
        if foreign and not real_pen_during:
            self.trip("R-FOREIGN", f"{len(foreign)} unexpected stroke(s) appeared in the student's layer "
                                   f"after a pen delivery, with the real pen idle")
        return foreign

    # ---------------------------------------------------------------- files
    def check_prefix(self, original: bytes, new: bytes):
        self.check_not_stopped()
        if not new.startswith(original):
            self.trip("R-PREFIX", "the new page file does not keep the student's bytes as its prefix")
