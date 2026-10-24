"""Writing with the pen path into a zoomed or scrolled page - and knowing that it landed.

Pen events land where the pen touches the SCREEN. The marks are planned in PAGE pixels. Between the
two sits the viewport (zoom and scroll), which nobody reports. Round 4 (2026-10-24):

1. Viewport from the tablet's own screenshot (the page thumbnail shows the page as displayed;
   `viewport.estimate`). Too weak a fit -> no writing (R-VIEWPORT).
2. Every point must map onto the screen with a margin; a mark off-screen waits (R-OFFSCREEN).
3. Probe first: the smallest measurable stroke goes alone. The page file is read back and the stroke
   that appeared is compared with where it was meant to go. The thumbnail can be stale (the student
   scrolled without writing - no new save, no new thumbnail); the probe is what catches that.
4. Probe within `tol` (8 px, under the foreign-stroke guard's 10 px) -> the rest follows, aimed by
   what the probe measured. Off -> stop: one small stray stroke instead of a whole
   misplaced note. The measured shift is kept and corrects the next attempt (R-PROBE).

Every stroke the pen path leaves - probes included - is the agent's, although it sits in the
student's layer. `landed` lists them, so the watcher can keep reading them as agent ink.
"""
from __future__ import annotations

import math
import time

from . import penstream, viewport
from .guards import GuardError

SCREEN = viewport.SCREEN


def _dbg_penpath(hypothesis_id: str, message: str, data: dict) -> None:
    # region agent log
    try:
        import json
        import time
        path = "/Users/samuelfleig/Projects/01_WORK/InkpartnerPairProgramming/.cursor/debug-79b8ba.log"
        line = json.dumps({"sessionId": "79b8ba", "hypothesisId": hypothesis_id,
                           "location": "penpath.py:deliver", "message": message, "data": data,
                           "timestamp": int(time.time() * 1000)})
        with open(path, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    # endregion


def stroke_sig(s: dict) -> str:
    """Identity of a saved stroke: first and last point and length (the device's own coordinates)."""
    p, q = s["points"][0], s["points"][-1]
    return f"{p[0]:.0f},{p[1]:.0f},{q[0]:.0f},{q[1]:.0f},{len(s['points'])}"


def new_strokes(before: list[dict], after: list[dict]) -> list[dict]:
    seen = {tuple(map(tuple, s["points"])) for s in before}
    return [s for s in after if tuple(map(tuple, s["points"])) not in seen]


def to_screen(strokes: list[dict], vp, margin: float = 40.0):
    """Page strokes -> screen strokes. A stroke that would leave the screen is left out, not sent.
    None if nothing remains on screen."""
    out = []
    for s in strokes:
        pts = [list(vp.to_screen(p[0], p[1])) for p in s["points"]]
        if any(not (margin <= x <= SCREEN[0] - margin and margin <= y <= SCREEN[1] - margin) for x, y in pts):
            continue
        out.append({k: v for k, v in s.items() if k != "points"} | {"points": penstream.densify(pts)})
    return out or None


def _bbox(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def clearance(stroke: dict, ink: list[dict]) -> float:
    """Distance from the stroke to the nearest student ink: how far a stale viewport may shift the
    probe before it touches the writing."""
    pts = [p for s in ink for p in s["points"][::4]]
    if not pts:
        return 1e9
    return min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in stroke["points"][::4] for p in pts)


def pick_probe(strokes: list[dict], ink: list[dict] = (), lo: float = 15.0, hi: float = 120.0) -> int:
    """The probe: big enough to measure shift and scale, small enough to be a minor stray if it
    misses, and with the most blank paper around it - a probe that misses should miss onto paper."""
    def diag(s):
        x0, y0, x1, y1 = _bbox(s["points"])
        return math.hypot(x1 - x0, y1 - y0)
    ok = [i for i, s in enumerate(strokes) if lo <= diag(s) <= hi] or list(range(len(strokes)))
    return max(ok, key=lambda i: (clearance(strokes[i], ink), -diag(strokes[i])))


def landing(expected: dict, appeared: list[dict]):
    """(dx, dy, scale ratio) of the appeared stroke against the planned one, page pixels; None if
    nothing appeared. With several new strokes the one closest in size and place is taken."""
    if not appeared:
        return None
    ex0, ey0, ex1, ey1 = _bbox(expected["points"])
    ec = ((ex0 + ex1) / 2, (ey0 + ey1) / 2)
    ed = max(1.0, math.hypot(ex1 - ex0, ey1 - ey0))
    best = None
    for s in appeared:
        x0, y0, x1, y1 = _bbox(s["points"])
        c, d = ((x0 + x1) / 2, (y0 + y1) / 2), math.hypot(x1 - x0, y1 - y0)
        cost = math.hypot(c[0] - ec[0], c[1] - ec[1]) + 2 * abs(d - ed)
        if best is None or cost < best[0]:
            best = (cost, c[0] - ec[0], c[1] - ec[1], d / ed)
    return best[1], best[2], best[3]


class PenPath:
    """`dev` is the tablet side: thumbnail(rel) -> png | None, fetch(rel) -> bytes,
    strokes(bytes) -> page strokes, send(screen strokes). The guard checks run before (watch.py)."""

    def __init__(self, dev, *, min_score=0.5, tol=8.0, wait_s=1.0, tries=8, sleep=time.sleep):
        self.dev, self.min_score, self.tol = dev, min_score, tol
        self.wait_s, self.tries, self.sleep = wait_s, tries, sleep
        self.correction = (0.0, 0.0)          # learned from the last probe that landed off ...
        self.correction_for = None            # ... valid only for the screenshot it was measured on
        self.landed: list[dict] = []          # strokes this path left on the page (probes included)
        self.last: dict = {}

    def viewport(self, rel, page_strokes):
        # first choice: the student's last strokes, seen on the screen and on the page (exact, and it
        # follows scrolling - the thumbnail shows the top of the page, found on the device 24.10.)
        known = getattr(self.dev, "known_viewport", None)
        vp, src = known(rel, page_strokes) if known else (None, None)
        if vp is not None:
            self.source = src
            return vp
        self.source = "thumbnail"
        png = self.dev.thumbnail(rel)
        if png is None:
            raise GuardError("R-VIEWPORT: no screenshot of the open page")
        user = [s for s in page_strokes if s.get("author") == "user"] or page_strokes
        vp = viewport.estimate(user, png)
        if vp.score < self.min_score:
            raise GuardError(f"R-VIEWPORT: screenshot fit too weak ({vp.score:.2f})")
        key = hash(png)
        if self.correction_for != key:              # a new screenshot: the old correction is void
            self.correction, self.correction_for = (0.0, 0.0), key
        vp.ox -= self.correction[0] * vp.scale        # the probe landed `correction` too far: aim back
        vp.oy -= self.correction[1] * vp.scale
        return vp

    def _after(self, rel, before, count):
        """Wait until the notes app has saved what was sent; returns (new strokes, page strokes)."""
        after = before
        for _ in range(self.tries):
            self.sleep(self.wait_s)
            after = self.dev.strokes(self.dev.fetch(rel))
            fresh = new_strokes(before, after)
            if len(fresh) >= count:
                return fresh, after
        return new_strokes(before, after), after

    def deliver(self, strokes: list[dict], rel: str) -> dict:
        self.landed, self.last = [], {}
        before = self.dev.strokes(self.dev.fetch(rel))
        vp = self.viewport(rel, before)
        screen = to_screen(strokes, vp)
        if screen is None and self.correction != (0.0, 0.0):
            # The shift from the last miss throws every mark off the screen (live 25.10.: 1615 px,
            # then R-OFFSCREEN). It cannot be applied; the raw fit is used instead.
            self.correction = (0.0, 0.0)
            vp = self.viewport(rel, before)
            screen = to_screen(strokes, vp)
        if screen is None:
            # region agent log
            _dbg_penpath("I", "offscreen", {"ox": round(vp.ox), "oy": round(vp.oy),
                                            "scale": round(vp.scale, 3), "score": round(vp.score, 2),
                                            "source": getattr(self, "source", "?")})
            # endregion
            raise GuardError("R-OFFSCREEN: the mark would leave the visible part of the page")
        on_screen = [s for s in strokes if to_screen([s], vp)]
        actions = [s.get("action") for s in on_screen]
        if getattr(self, "source", "") in ("pen", "remembered"):
            # the viewport is measured, not guessed, and no finger moved the page since: no probe.
            # The app saves pen strokes up to a minute late (live test 24.10.) - a probe would cost that.
            self.dev.send(screen)
            self.last = {"viewport": [round(vp.scale, 3), round(vp.ox), round(vp.oy), round(vp.score, 2)],
                         "source": self.source}
            return {"status": "sent_direct", "strokes": len(screen), "actions": actions, **self.last}
        i = pick_probe(on_screen, [s for s in before if s.get("author") == "user"])
        self.dev.send([screen[i]])
        fresh, after = self._after(rel, before, 1)
        self.landed += fresh
        got = landing(on_screen[i], fresh)
        self.last = {"viewport": [round(vp.scale, 3), round(vp.ox), round(vp.oy), round(vp.score, 2)],
                     "source": getattr(self, "source", "?")}
        if got is None:
            # maybe it arrived and is not saved yet: never send again blindly
            raise GuardError("R-PROBE: the probe stroke did not appear")
        dx, dy, ratio = got
        err = math.hypot(dx, dy)
        self.last["probe_error_px"] = round(err, 1)
        # region agent log
        _dbg_penpath("G", "probe landing", {"dx": round(dx), "dy": round(dy), "err": round(err),
                                            "ratio": round(ratio, 3), "fresh": len(fresh),
                                            "ox": round(vp.ox), "oy": round(vp.oy),
                                            "scale": round(vp.scale, 3), "score": round(vp.score, 2),
                                            "source": getattr(self, "source", "?")})
        # endregion
        if err > self.tol or not 0.85 <= ratio <= 1.15:
            self.correction = (self.correction[0] + dx, self.correction[1] + dy)
            raise GuardError(f"R-PROBE: probe landed {err:.0f} px off (scale x{ratio:.2f}); "
                             f"correction kept for the next attempt")
        # the probe says exactly where ink lands: aim the rest by what it measured
        rest = [{"points": [[x - dx * vp.scale, y - dy * vp.scale] for x, y in (p[:2] for p in s["points"])]}
                for j, s in enumerate(screen) if j != i]
        if rest:
            self.dev.send(rest)
            fresh, after = self._after(rel, after, len(rest))
            self.landed += fresh
        self.correction = (0.0, 0.0)
        return {"status": "sent_probed", "strokes": len(screen), "actions": actions, **self.last}
