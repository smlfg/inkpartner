"""Snap the model's boxes to the real ink.

Simulation round 2: the boxes a vision model returns cover the true line only to ~25 % (IoU) - and
marks are drawn at those boxes, so a red circle lands next to the line it means. The strokes are
known exactly; the model only has to say roughly where. Every student stroke goes to the element
whose (enlarged) box holds its centre, nearest box first; the element's box becomes the union of its
strokes. An element with no strokes keeps the model's box.
"""
from __future__ import annotations

from .elements import Element


def _bbox(s):
    xs = [p[0] for p in s["points"]]
    ys = [p[1] for p in s["points"]]
    return min(xs), min(ys), max(xs), max(ys)


def snap(elements: list[Element], strokes: list[dict], grow: float = 0.6) -> list[Element]:
    student = [s for s in strokes if s.get("author", "user") == "user" and s["points"]]
    if not elements or not student:
        return elements
    owned: dict[str, list] = {e.id: [] for e in elements}
    for s in student:
        x0, y0, x1, y1 = _bbox(s)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        best, best_d = None, None
        for e in elements:
            bx0, by0, bx1, by1 = e.bbox
            h, w = max(20.0, by1 - by0), max(20.0, bx1 - bx0)
            gx, gy = w * grow * 0.5, h * grow
            if not (bx0 - gx <= cx <= bx1 + gx and by0 - gy <= cy <= by1 + gy):
                continue
            d = abs(cy - (by0 + by1) / 2) / h + 0.25 * abs(cx - (bx0 + bx1) / 2) / w
            if best_d is None or d < best_d:
                best, best_d = e, d
        if best is not None:
            owned[best.id].append((x0, y0, x1, y1))
    for e in elements:
        boxes = owned[e.id]
        if boxes:
            e.bbox = [min(b[0] for b in boxes), min(b[1] for b in boxes),
                      max(b[2] for b in boxes), max(b[3] for b in boxes)]
    return elements
