"""The agent measures the viewport with its own stroke - nobody has to write first.

Live test 24.10.: measuring from the student's strokes meant "write again, write again". Instead the
agent draws a small, lopsided L at a free corner of the screen, waits until the notes app has saved
it, and finds it in the page file. Screen points (sent) against page points (saved) give scale,
scroll and rotation (an L cannot be confused with its turned or mirrored self: the legs differ).
The result is kept in ~/.cache/inkpartner/calib.json and used until a finger touches the screen.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import penstream, viewport

CALIB = Path(os.path.expanduser("~/.cache/inkpartner/calib.json"))


def l_shape(corner=(1470.0, 1930.0), down=110.0, right=60.0) -> list[list[float]]:
    x, y = corner
    return penstream.densify([[x, y], [x, y + down], [x + right, y + down]])


def measure(sent: list, saved: list) -> tuple:
    """(viewport, rms) of the saved stroke against the sent screen points."""
    vp, rms = viewport._fit([sent], [{"points": saved}])
    return vp, rms


def run(tablet, rel: str, wait_s: float = 120.0, log=print):
    """Draw the L on the open page, wait for the save, fit. Returns the viewport or None."""
    before = tablet.strokes(tablet.fetch(rel))
    seen = {tuple(map(tuple, s["points"])) for s in before}
    pts = l_shape()
    tablet.send([{"points": pts}])
    log("calibration L sent - waiting for the notes app to save it")
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(2)
        new = [s for s in tablet.strokes(tablet.fetch(rel)) if tuple(map(tuple, s["points"])) not in seen]
        if new:
            stroke = max(new, key=lambda s: len(s["points"]))
            vp, rms = measure(pts, stroke["points"])
            log(f"L found after {time.time() - t0:.0f}s: scale {vp.scale if vp else None}, turn {vp.turn if vp else None}, rms {rms:.1f}")
            if vp is not None and rms < 8:
                save(rel, vp, stroke)
                return vp
            return None
    log("the L did not appear in the file")
    return None


def save(rel, vp, stroke):
    CALIB.parent.mkdir(parents=True, exist_ok=True)
    CALIB.write_text(json.dumps({"rel": rel, "scale": vp.scale, "ox": vp.ox, "oy": vp.oy,
                                 "turn": [vp.turn.real, vp.turn.imag], "t": time.time(),
                                 "stroke": stroke["points"]}))


def load(rel: str):
    """(viewport, time, the L's saved points) for this page, or None."""
    try:
        d = json.loads(CALIB.read_text())
    except (OSError, ValueError):
        return None
    if d.get("rel") != rel:
        return None
    vp = viewport.Viewport(d["scale"], d["ox"], d["oy"], 1.0, turn=complex(*d["turn"]))
    return vp, d["t"], d.get("stroke", [])
