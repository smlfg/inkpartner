"""Did the ink arrive? Three answers, never two: confirmed, missing, unclear.

"Sent" is not "written" (device test 2026-10-20: the pen path reported an error and the line was
there anyway; the reverse happens too). After every delivery the page is read back and each action
is checked against the strokes that appeared since. "unclear" means: do not write it again yet -
it may already be on the page, and a duplicate mark is worse than a late one.
"""
from __future__ import annotations

import math


def _near(a, b, tol):
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol


def coverage(expected: dict, candidates: list[dict], tol: float = 8.0) -> float:
    """Share of the expected stroke's points that lie on some candidate stroke."""
    pts = expected["points"]
    hits = 0
    cand = [p for s in candidates for p in s["points"]]
    for p in pts:
        if any(_near(p, q, tol) for q in cand):
            hits += 1
    return hits / max(1, len(pts))


def verify(expected: list[dict], before: list[dict], after: list[dict], *,
           confirm_at: float = 0.85, missing_below: float = 0.15) -> dict[str, str]:
    """action key -> 'confirmed' | 'missing' | 'unclear'.

    Only strokes that are new since `before` count. Colour and layer are deliberately ignored: the
    pen path writes in the student's layer and colour, the file path in the agent layer - both are
    real ink on the page.
    """
    seen = {tuple(map(tuple, s["points"])) for s in before}
    new = [s for s in after if tuple(map(tuple, s["points"])) not in seen]
    by_action: dict[str, list[dict]] = {}
    for s in expected:
        by_action.setdefault(s["action"], []).append(s)
    out = {}
    for key, strokes in by_action.items():
        score = sum(coverage(s, new) for s in strokes) / len(strokes)
        out[key] = "confirmed" if score >= confirm_at else "missing" if score <= missing_below else "unclear"
    return out
