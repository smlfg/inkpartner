"""The ways the agent can answer on paper. One vocabulary for every subject.

| mark       | meaning                                   | default colour |
|------------|-------------------------------------------|----------------|
| check      | this is right (Haken)                     | green          |
| underline  | right (green) or wrong (red)              | green / red    |
| circle     | here is the mistake                       | red            |
| wavy       | I cannot read this - write it again       | gray           |
| question   | think about this spot again               | blue           |
| arrow      | points from a note to its element         | colour of note |
| note       | short handwritten text: correction (red) or hint (blue) | red / blue |

Every function returns strokes (page pixels) and touches nothing else: the student's ink is never
erased or rewritten. Text is written with a single-stroke Hershey font, so it looks like pen ink.
"""
from __future__ import annotations

import math

COLOR = {"check": "green", "underline": "green", "circle": "red", "wavy": "gray",
         "question": "blue", "note": "blue", "arrow": "blue"}
WIDTH = 3.0


def _stroke(points, color, width=WIDTH):
    return {"points": [[round(x, 1), round(y, 1), 0.7] for x, y in points], "color": color,
            "width": width, "author": "agent"}


def check(bbox, color="green"):
    x0, y0, x1, y1 = bbox
    h = max(24.0, min(60.0, y1 - y0))
    x = x1 + 18
    y = (y0 + y1) / 2
    return [_stroke([(x, y), (x + h * 0.3, y + h * 0.35), (x + h * 0.9, y - h * 0.45)], color, 4)]


def underline(bbox, color="green"):
    x0, _, x1, y1 = bbox
    return [_stroke([(x0, y1 + 8), (x1, y1 + 8)], color)]


def wavy(bbox, color="gray"):
    x0, _, x1, y1 = bbox
    pts, x, amp, step = [], x0, 5.0, 4.0
    while x <= x1:
        pts.append((x, y1 + 10 + amp * math.sin((x - x0) / 9.0)))
        x += step
    return [_stroke(pts, color)]


def circle(bbox, color="red"):
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2 + 14, (y1 - y0) / 2 + 12
    # a little overlap at the end, like a hand-drawn loop
    pts = [(cx + rx * math.cos(t), cy + ry * math.sin(t)) for t in
           (2 * math.pi * i / 48 - 0.4 for i in range(53))]
    return [_stroke(pts, color)]


def arrow(start, end, color="blue"):
    (sx, sy), (ex, ey) = start, end
    a = math.atan2(ey - sy, ex - sx)
    head = 16
    left = (ex - head * math.cos(a - 0.45), ey - head * math.sin(a - 0.45))
    right = (ex - head * math.cos(a + 0.45), ey - head * math.sin(a + 0.45))
    return [_stroke([(sx, sy), (ex, ey)], color), _stroke([left, (ex, ey), right], color)]


_FONT = None
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
                       "·": "*", "−": "-", "→": "->", "≠": "!="})


def _font():
    global _FONT
    if _FONT is None:
        from HersheyFonts import HersheyFonts
        _FONT = HersheyFonts()
        _FONT.load_default_font("futural")
        _FONT.normalize_rendering(100)
    return _FONT


def text_size(text: str, height: float = 34.0) -> tuple[float, float]:
    xs = [x for s in _font().strokes_for_text(text.translate(_FOLD)) for x, _ in s]
    return (max(xs, default=0) * height / 100.0, height)


def text(s: str, origin, height: float = 34.0, color="blue"):
    """Single-stroke handwriting, top-left at `origin`. Hershey y grows upward, the page downward."""
    ox, oy = origin
    k = height / 100.0
    return [_stroke([(ox + x * k, oy + height - y * k) for x, y in stroke], color, 2.5)
            for stroke in _font().strokes_for_text(s.translate(_FOLD)) if len(stroke) > 1]


def wrap(s: str, width: int) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


def question(bbox, color="blue"):
    x0, y0, x1, y1 = bbox
    return text("?", (x1 + 14, y0 - 6), height=max(30.0, min(56.0, y1 - y0)), color=color)


def bbox_of(strokes) -> list[float]:
    xs = [p[0] for s in strokes for p in s["points"]]
    ys = [p[1] for s in strokes for p in s["points"]]
    return [min(xs), min(ys), max(xs), max(ys)]
