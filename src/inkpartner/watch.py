"""The watcher: finds where the student is writing, reviews when the pen rests, writes back without
ever throwing them out of the notebook.

Where is the student writing? Nobody tells the agent. Every few seconds it lists the modification
time and size of every page file on the tablet (one SSH call). The page that changed last is the
page being written on - in any notebook, also a new one. Measured 2026-10-23: a notebook opened a
minute earlier ("inkpartnertest") was the newest file at once. The tablet saves while writing, not
only on close (save probe, 2026-10-20). `lastOpened` in the metadata is NOT used: it lags until the
notebook is closed.

The agent's own writes change the file too. Every page the agent wrote is remembered with the hash
it left behind; a change that only shows that hash is the agent's echo, not the student.

How to write back:
- pen  (V-Pen, algebra-agent/inject.py): pen events into the open page. No restart, never throws the
  student out. Price: the ink takes the colour of the pen currently selected and lands in the
  student's layer. Needs the viewport calibration (~/.config/penecho/live_viewport.json).
- file (append an agent layer + restart the notes app): colour and own layer, but a restart - and a
  restart LOGS THE STUDENT OUT (seen 2026-10-23: back to the passcode screen). Last resort only:
  off unless --allow-restart, then only after `restart_quiet_s` (default 30 min) without any change
  on ANY page, at most once per `restart_gap_s` (default 1 h). A quiet page is not an idle student -
  on 2026-10-23 the student sat reading the page for 4 minutes and was thrown out.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import page as pagemod
from . import review, verify

XOCHITL = "/home/root/.local/share/remarkable/xochitl"
CALIBRATION = Path(os.environ.get("PENECHO_LIVE_CALIBRATION",
                                  Path.home() / ".config/penecho/live_viewport.json"))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Tablet:
    """Everything that touches the tablet, over SSH. Reads are free; writes are two: pen events into
    /dev/input/<pen> (pen path) and one page file + restart (file path)."""

    def __init__(self, host: str = "remarkable"):
        self.host = host

    def ssh(self, cmd: str, data: bytes | None = None, timeout: float = 30) -> bytes:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", self.host, cmd],
                           input=data, capture_output=True, timeout=timeout)
        if r.returncode != 0 and not (data and b"Invalid argument" in r.stderr):
            raise RuntimeError(r.stderr.decode(errors="replace").strip() or f"ssh exit {r.returncode}")
        return r.stdout

    def scan(self) -> dict[str, tuple[int, int]]:
        """page path (doc/page.rm) -> (mtime, size) for every page on the tablet. The tablet's own
        clock comes along ('now'), so ages are measured on one clock, not across two devices."""
        out = self.ssh(f"date +%s; cd {XOCHITL} && stat -c '%Y %s %n' */*.rm 2>/dev/null; true")
        lines = out.decode().splitlines()
        self.clock = int(lines[0]) if lines and lines[0].isdigit() else int(time.time())
        pages = {}
        for line in lines[1:]:
            parts = line.split(" ", 2)
            if len(parts) == 3:
                pages[parts[2]] = (int(parts[0]), int(parts[1]))
        return pages

    def fetch(self, rel: str) -> bytes:
        return self.ssh(f"cat {shlex.quote(XOCHITL + '/' + rel)}")

    def name(self, rel: str) -> str:
        doc = rel.split("/")[0]
        try:
            return json.loads(self.ssh(f"cat {XOCHITL}/{doc}.metadata"))["visibleName"]
        except Exception:
            return doc

    def write_file_and_restart(self, rel: str, data: bytes, expected_sha: str):
        """File path. Checks the page is still what was reviewed right before stopping the app."""
        if sha(self.fetch(rel)) != expected_sha:
            raise RuntimeError("page changed since review - not restarting")
        target = shlex.quote(XOCHITL + "/" + rel)
        self.ssh(f"systemctl stop xochitl && cat > {target}.inkpartner && mv {target}.inkpartner {target}"
                 f" ; systemctl start xochitl", data=data, timeout=60)


class PenChannel:
    """Pen events into the open page (idea and device facts from algebra-agent's V-Pen; the event
    stream itself is penstream.py, rebuilt after firmware 20261009 stopped accepting the old one).
    Strokes in page pixels; the viewport calibration maps them to the screen."""

    def __init__(self, tablet: Tablet, device: str | None = None):
        self.tablet = tablet
        self.cal = json.loads(CALIBRATION.read_text())   # no calibration -> no pen path (raises)
        self.device = device or self.cal.get("device", "event2")

    def deliver(self, strokes: list[dict]) -> dict:
        from . import penstream
        sx, sy = float(self.cal["scale"]), float(self.cal.get("scale_y", self.cal["scale"]))
        ox, oy = float(self.cal["offset_x"]), float(self.cal["offset_y"])
        screen = [{"points": penstream.densify([[p[0] * sx + ox, p[1] * sy + oy] for p in s["points"]])}
                  for s in strokes]
        stream = penstream.build(screen)
        # `cat` reports EINVAL on this device even when every event arrives (algebra-agent, 20.10.):
        # the exit code says nothing - only reading the page back does.
        self.tablet.ssh(f"cat > /dev/input/{shlex.quote(self.device)}", data=stream, timeout=60)
        return {"status": "sent_unverified", "bytes": len(stream), "strokes": len(screen)}


@dataclass
class PageState:
    stamp: tuple[int, int]
    last_change: float
    reviewed_sha: str = ""
    own_sha: str = ""                                   # what the agent itself left on the page
    delivered: set[str] = field(default_factory=set)
    pending: dict | None = None                         # feedback that could not be written yet


class Watcher:
    def __init__(self, tablet: Tablet, model, *, subject=None, settle_s=4.0, restart_quiet_s=1800.0,
                 allow_restart=False, recent_s=600.0, pen=True, log=print, state_file=None,
                 speak=None, speech_allowed=False, pen_rest_s=900.0, restart_gap_s=3600.0):
        self.tablet, self.model, self.subject = tablet, model, subject
        self.settle_s, self.restart_quiet_s, self.allow_restart = settle_s, restart_quiet_s, allow_restart
        self.recent_s = recent_s
        self.log = log
        self.pages: dict[str, PageState] = {}
        self.pen = None
        if pen is True:
            try:
                self.pen = PenChannel(tablet)
            except Exception as e:
                self.log(f"pen path unavailable ({e}); only the file path when the page is quiet")
        elif pen:
            self.pen = pen
        self.verify_tries, self.verify_wait_s = 5, 2.0
        self.speak, self.speech_allowed = speak, speech_allowed
        self.pen_failures, self.pen_rest_until, self.pen_rest_s = 0, 0.0, pen_rest_s
        self.restart_gap_s, self.last_restart = restart_gap_s, -1e18
        self.state_file = Path(state_file or Path.home() / ".cache/inkpartner/state.json")
        self._load()

    # ------------------------------------------------------------------ state
    def _load(self):
        try:
            data = json.loads(self.state_file.read_text())
            for rel, d in data.items():
                self.pages[rel] = PageState(tuple(d["stamp"]), 0.0, d["reviewed_sha"], d["own_sha"],
                                            set(d["delivered"]))
        except (OSError, ValueError, KeyError):
            pass

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({rel: {"stamp": p.stamp, "reviewed_sha": p.reviewed_sha,
                                                     "own_sha": p.own_sha, "delivered": sorted(p.delivered)}
                                               for rel, p in self.pages.items()}))

    # ------------------------------------------------------------------- loop
    def tick(self):
        stamps = self.tablet.scan()
        now = self.tablet.clock                         # tablet time: mtimes are tablet time too
        first = not any(p.last_change for p in self.pages.values()) and not getattr(self, "_started", False)
        self._started = True
        for rel, stamp in stamps.items():
            st = self.pages.get(rel)
            if st is None or (first and st.last_change == 0.0):
                # at start, a page written in the last few minutes is still "current"; older is old news
                recent = now - stamp[0] <= self.recent_s
                if st is None:
                    st = self.pages[rel] = PageState(stamp, 0.0)
                st.stamp = stamp
                st.last_change = float(stamp[0]) if (recent or not first) else 0.0
                if not first:
                    self.log(f"new page: {self.tablet.name(rel)} ({rel})")
            elif st.stamp != stamp:
                st.stamp, st.last_change = stamp, now
        # escalation: feedback that could not be written waits here until a safe path is open
        for rel, st in self.pages.items():
            if st.pending:
                self.retry_pending(rel, st, now)
        # the page that changed last and has rested for settle_s is reviewed
        active = max(self.pages.items(), key=lambda kv: kv[1].last_change, default=(None, None))
        rel, st = active
        if rel is None or st.last_change == 0.0 or now - st.last_change < self.settle_s:
            return None
        data = self.tablet.fetch(rel)
        h = sha(data)
        if h in (st.reviewed_sha, st.own_sha):
            return None                                 # nothing new, or only the agent's own echo
        return self.review(rel, st, data, h, now)

    def review(self, rel: str, st: PageState, data: bytes, h: str, now: float):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "page.rm")
            Path(src).write_bytes(data)
            strokes = pagemod.read_strokes(src)
            t0 = time.time()
            r = review.run(strokes, model=self.model, subject=self.subject, delivered=st.delivered)
            self.log(f"{self.tablet.name(rel)}: {r.subject}, {len(r.elements)} elements, "
                     f"{len(r.accepted)} marks in {time.time() - t0:.1f}s via {getattr(self.model, 'used', '?')}")
            for a in r.accepted:
                self.log(f"  {a.verdict:10} {a.mark:9} {a.element} {a.text!r}")
            for a, why in r.rejected:
                self.log(f"  rejected   {a.mark:9} {a.element}: {why}")
            st.reviewed_sha = h
            if not r.strokes:
                self._save()
                return r
            if self.tablet.fetch(rel) != data:
                self.log("  student wrote meanwhile - feedback dropped, next round")
                st.reviewed_sha = ""
                return r
            result = self.deliver(rel, st, src, data, h, r, now)
            self.log(f"  delivery: {result}")
            self._save()
            return r

    def deliver(self, rel, st, src, data, h, r, now) -> dict:
        """Escalation (Codex session 2026-10-23): pen -> verify -> on failure rest the pen path and keep
        the feedback pending -> file path once the page is quiet (never while writing) -> speech if
        allowed -> otherwise wait and retry later. Never counted as done unless read back."""
        result = {}
        missing = list(r.strokes)
        if self.pen is not None and now >= self.pen_rest_until:
            sent = self.pen.deliver(r.strokes)
            before = pagemod.read_strokes(src)
            states, after_bytes = {}, data
            for _ in range(self.verify_tries):              # xochitl saves the pen strokes itself, a bit later
                time.sleep(self.verify_wait_s)
                after_bytes = self.tablet.fetch(rel)
                with tempfile.TemporaryDirectory() as tmp:
                    a = os.path.join(tmp, "after.rm")
                    Path(a).write_bytes(after_bytes)
                    after = pagemod.read_strokes(a)
                states = verify.verify(r.strokes, before, after)
                if all(v == "confirmed" for v in states.values()):
                    break
            st.own_sha = sha(after_bytes)
            st.delivered |= {k for k, v in states.items() if v == "confirmed"}
            result = {"path": "pen", "sent": sent.get("status"), "verified": states}
            if all(v == "confirmed" for v in states.values()):
                self.pen_failures = 0
                return result
            # only what is surely missing may be written again; 'unclear' may already be on the page
            missing = [s for s in r.strokes if states.get(s["action"]) == "missing"]
            if all(v == "missing" for v in states.values()):
                self.pen_failures += 1
                if self.pen_failures >= 2:
                    self.pen_rest_until = now + self.pen_rest_s
                    self.log(f"  pen path failed {self.pen_failures}x in a row - resting it for "
                             f"{self.pen_rest_s / 60:.0f} min")
        if missing:
            speech = " ".join(v for k, v in r.speech.items() if any(s["action"] == k for s in missing))
            st.pending = {"strokes": missing, "base_sha": sha(self.tablet.fetch(rel)), "speech": speech,
                          "since": now}
            result["pending"] = len({s["action"] for s in missing})
            self.retry_pending(rel, st, now)
        return result

    def retry_pending(self, rel, st, now):
        p = st.pending
        current = self.tablet.fetch(rel)
        if sha(current) != p["base_sha"]:
            self.log(f"  {self.tablet.name(rel)}: page changed since - pending feedback dropped (stale)")
            st.pending = None
            st.reviewed_sha = ""                          # look at the page again
            return
        # idle = no change on ANY page; a page the student only reads is quiet but not idle
        quiet = now - max(x.last_change for x in self.pages.values())
        if (self.allow_restart and quiet >= self.restart_quiet_s
                and now - self.last_restart >= self.restart_gap_s):
            self.last_restart = now
            with tempfile.TemporaryDirectory() as tmp:
                src, out = os.path.join(tmp, "in.rm"), os.path.join(tmp, "out.rm")
                Path(src).write_bytes(current)
                pagemod.append_strokes(src, p["strokes"], out)
                new = Path(out).read_bytes()
            self.tablet.write_file_and_restart(rel, new, p["base_sha"])
            back = self.tablet.fetch(rel)
            st.own_sha = sha(back)
            if back == new:
                st.delivered |= {s["action"] for s in p["strokes"]}
                st.pending = None
                self.log(f"  {self.tablet.name(rel)}: written via file path (page quiet {quiet:.0f}s), verified")
            else:
                self.log(f"  {self.tablet.name(rel)}: file path did not verify - stays pending")
            self._save()
            return
        if p.get("speech") and self.speak and self.speech_allowed and not p.get("spoken"):
            self.speak(p["speech"])
            p["spoken"] = True
            self.log("  spoken while writing is not possible")


def run(host="remarkable", model=None, subject=None, interval_s=3.0, once=False, **kw):
    """Loop forever (or until the first review with --once)."""
    from . import models
    w = Watcher(Tablet(host), models.get(model), subject=subject, **kw)
    w.log(f"watching {host} every {interval_s}s with {w.model.name}; pen path: {'yes' if w.pen else 'no'}")
    while True:
        try:
            r = w.tick()
            if once and r is not None:
                return r
        except KeyboardInterrupt:
            raise
        except Exception as e:
            w.log(f"error: {e}")
        time.sleep(interval_s)
