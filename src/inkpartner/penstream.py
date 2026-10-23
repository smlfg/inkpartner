"""Pen events the way the real Marker sends them on firmware 20261009.

Recorded from Samuel's own pen on 2026-10-23 (read-only, `cat /dev/input/event2`):
    ... ABS_DISTANCE ABS_TILT_X ABS_TILT_Y SYN   (hovering)
    BTN_TOUCH=1 ABS_PRESSURE=215 ABS_X ABS_Y SYN  (pen down)
    ABS_X ABS_Y [ABS_PRESSURE] SYN  ... every ~1.8 ms
    BTN_TOUCH=0 ABS_PRESSURE=0 ABS_DISTANCE SYN   (pen up)
algebra-agent's stream (inject.py, verified on firmware 20260121) has no BTN_TOUCH at all. On
20261009 xochitl then logs "Timeout while waiting for penpoint" and draws nothing - the pen never
touched down. This stream adds the touch, a short hover before and after, and real-pen timing.
"""
from __future__ import annotations

import struct
import time

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT = 0
BTN_TOOL_PEN, BTN_TOUCH = 320, 330
ABS_X, ABS_Y, ABS_PRESSURE, ABS_DISTANCE, ABS_TILT_X, ABS_TILT_Y = 0, 1, 24, 25, 26, 27
DIGITIZER = (11180, 15340)        # ABS_X / ABS_Y maximum (algebra-agent, measured 2026-10-20)
PAGE = (1620, 2160)
FMT = "<qqHHi"                    # struct input_event on aarch64: 24 bytes
STEP_US = 1800                    # the real pen reports every ~1.8 ms
HOVER_DISTANCE = 25000            # ABS_DISTANCE seen while the real pen hovers
PRESSURE = 1800                   # mid of the real pen's range (215 at touch-down, up to ~2600)


def to_digitizer(x: float, y: float) -> tuple[int, int]:
    dx = round(x / PAGE[0] * DIGITIZER[0])
    dy = round(y / PAGE[1] * DIGITIZER[1])
    return max(0, min(DIGITIZER[0], dx)), max(0, min(DIGITIZER[1], dy))


def build(strokes, start: float | None = None) -> bytes:
    t = int((time.time() if start is None else start) * 1e6)
    out = bytearray()

    def ev(etype, code, value):
        out.extend(struct.pack(FMT, t // 1_000_000, t % 1_000_000, etype, code, value))

    def syn():
        nonlocal t
        ev(EV_SYN, SYN_REPORT, 0)
        t += STEP_US

    for s in strokes:
        pts = [to_digitizer(p[0], p[1]) for p in s["points"]]
        if not pts:
            continue
        x0, y0 = pts[0]
        ev(EV_KEY, BTN_TOOL_PEN, 1)                       # pen comes into range, hovering
        ev(EV_ABS, ABS_X, x0); ev(EV_ABS, ABS_Y, y0)
        ev(EV_ABS, ABS_DISTANCE, HOVER_DISTANCE); ev(EV_ABS, ABS_TILT_X, 0); ev(EV_ABS, ABS_TILT_Y, 0)
        syn()
        ev(EV_KEY, BTN_TOUCH, 1)                          # pen down: the event the old stream lacked
        ev(EV_ABS, ABS_PRESSURE, PRESSURE); ev(EV_ABS, ABS_DISTANCE, 0)
        ev(EV_ABS, ABS_X, x0); ev(EV_ABS, ABS_Y, y0)
        syn()
        for x, y in pts[1:]:
            ev(EV_ABS, ABS_X, x); ev(EV_ABS, ABS_Y, y)
            syn()
        x1, y1 = pts[-1]
        ev(EV_KEY, BTN_TOUCH, 0)                          # pen up
        ev(EV_ABS, ABS_PRESSURE, 0); ev(EV_ABS, ABS_DISTANCE, HOVER_DISTANCE)
        syn()
        ev(EV_KEY, BTN_TOOL_PEN, 0)                       # out of range
        syn()
        t += 20_000                                       # 20 ms between strokes, like lifting the pen
    return bytes(out)


def densify(points, step: float = 4.0):
    """The real pen reports a point every few pixels; long straight segments are filled in."""
    out = []
    for a, b in zip(points, points[1:]):
        n = max(1, int(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 / step))
        out += [[a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n] for k in range(n)]
    return out + [list(points[-1][:2])] if points else out
