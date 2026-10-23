"""Where a note goes. Prefer free paper next to the element; never refuse to write.

Lesson from the device (Codex session 2026-10-23): a writer that insists on pixel-perfect free space
blocks and writes nothing. So placement degrades instead of failing: free space right of the
element -> below it -> anywhere free on the page -> right of it even if that overlaps ink.
"""
from __future__ import annotations

CELL = 20


class Occupancy:
    def __init__(self, strokes, width: int, height: int):
        self.w, self.h = width, height
        self.cells: set[tuple[int, int]] = set()
        for s in strokes:
            self.add_points(s["points"], pad=6)

    def add_points(self, points, pad=6):
        for p in points:
            for dx in (-pad, 0, pad):
                for dy in (-pad, 0, pad):
                    self.cells.add((int((p[0] + dx) // CELL), int((p[1] + dy) // CELL)))

    def add_rect(self, r):
        x0, y0, x1, y1 = r
        for cx in range(int(x0 // CELL), int(x1 // CELL) + 1):
            for cy in range(int(y0 // CELL), int(y1 // CELL) + 1):
                self.cells.add((cx, cy))

    def free(self, r) -> bool:
        x0, y0, x1, y1 = r
        if x0 < 10 or y0 < 10 or x1 > self.w - 10 or y1 > self.h - 10:
            return False
        return not any((cx, cy) in self.cells for cx in range(int(x0 // CELL), int(x1 // CELL) + 1)
                       for cy in range(int(y0 // CELL), int(y1 // CELL) + 1))


def place(size, target, occ: Occupancy) -> dict:
    """Return {'rect', 'how', 'adjacent'} for a note of `size` (w, h) about `target` bbox."""
    w, h = size
    x0, y0, x1, y1 = target
    near = [(x1 + 60, y0 + (y1 - y0 - h) / 2, "right"),     # 60 px leaves room for a check/question mark
            (x0, y1 + 24, "below"),
            (x0, y0 - h - 24, "above")]
    for x, y, how in near:
        r = [x, y, x + w, y + h]
        if occ.free(r):
            return {"rect": r, "how": how, "adjacent": True}
    cy = y0
    for step in range(0, int(occ.h), CELL * 2):
        for y in (cy + step, cy - step):
            for x in range(20, int(occ.w - w - 20), CELL * 2):
                r = [x, y, x + w, y + h]
                if occ.free(r):
                    return {"rect": r, "how": "free-space", "adjacent": False}
    x = min(x1 + 60, occ.w - w - 10)
    r = [x, y0, x + w, y0 + h]
    return {"rect": r, "how": "overlap", "adjacent": True}
