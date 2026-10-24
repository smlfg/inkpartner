"""Turn accepted actions into strokes. The rules live in plan.py; this module only places the ink.

Each stroke carries the key of its action, so the verifier can later tell which action did or
did not arrive. Colour still comes from the verdict, never from the model.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from . import layout, marks
from .elements import Element

if TYPE_CHECKING:
    from .plan import Action


def draw(actions: list[Action], elements: list[Element], strokes_on_page: list[dict], *,
         width: int, height: int) -> list[dict]:
    """Turn accepted actions into strokes. Each stroke carries the key of its action, so the
    verifier can later tell which action did or did not arrive."""
    by_id = {e.id: e for e in elements}
    occ = layout.Occupancy(strokes_on_page, width, height)
    out = []
    for a in actions:
        el = by_id[a.element]
        if a.mark == "note":
            # as tall as the student's own letters, within reason (real page: ~100 px letters)
            h = max(34.0, min(80.0, 0.6 * (el.bbox[3] - el.bbox[1])))
            lines = marks.wrap(a.text, 28)
            w = max(marks.text_size(line, h)[0] for line in lines)
            spot = layout.place((w, h * 1.5 * len(lines)), el.bbox, occ)
            ink = []
            for i, line in enumerate(lines):
                ink += marks.text(line, (spot["rect"][0], spot["rect"][1] + i * h * 1.5), height=h, color=a.color)
            if not spot["adjacent"]:
                # from the edge of the note that faces the element to the edge of the element that
                # faces the note - an arrow that starts inside the note crosses its own text
                r, b = spot["rect"], el.bbox
                c_el = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
                c_note = ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)
                start = (min(max(c_el[0], r[0]), r[2]), min(max(c_el[1], r[1] - 8), r[3] + 8))
                end = (min(max(c_note[0], b[0] - 8), b[2] + 8), min(max(c_note[1], b[1] - 8), b[3] + 8))
                ink += marks.arrow(start, end, color=a.color)
        else:
            ink = getattr(marks, a.mark)(el.bbox, color=a.color)
        for s in ink:
            s["action"] = a.key(el)
            occ.add_points(s["points"])
        out += ink
    return out
