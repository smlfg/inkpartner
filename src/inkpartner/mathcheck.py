"""Deterministic step check for algebra: is each line still true for the task it belongs to?

The model is good at reading and at explaining, unreliable at deciding whether 3x+2=15 follows from
3(x+2)=15 (device test 2026-10-20: right place, wrong reason). Where sympy can decide, sympy decides
and the model's verdict must agree. Where sympy cannot parse a line, there is no override.

Every equation is compared with the task (the first equation of its exercise), not with the line
right above it. A real page (Lernen, 2026-10-23) showed why: Samuel computed 1 + 9/4 = 18/13,
noticed, drew a line and started over. Compared step by step, the correct restart would look wrong;
compared with the task, the restart is right and only the lines built on 18/13 are wrong.
- equation:      correct if its solutions are a non-empty subset of the task's solutions
                 (x = sqrt(13/4) - 3/2 is right: it is one of the two solutions)
- number chain:  1 + 9/4 = 4/4 + 9/4 = 13/4 is checked on its own: all sides equal
- "= ..." line:  continues the right side of the line above
- expression:    equal to the first expression of the exercise
"""
from __future__ import annotations

import re

from .elements import Element


def _parse(side: str):
    from sympy.parsing.sympy_parser import (parse_expr, standard_transformations,
                                            implicit_multiplication_application, convert_xor)
    s = (side.replace("·", "*").replace("×", "*").replace("−", "-").replace(":", "/")
         .replace(",", ".").replace("√", "sqrt").replace("{", "(").replace("}", ")")
         .replace("\\cdot", "*").replace("\\sqrt", "sqrt"))
    s = re.sub(r"\s+", "", s)
    if not s:
        raise ValueError("empty")
    return parse_expr(s, transformations=standard_transformations
                      + (implicit_multiplication_application, convert_xor))


def _variants(t: str) -> list[str]:
    """'x+3/2 = ±sqrt(13/4)' -> both signs."""
    for pm in ("±", "+-", "+/-"):
        if pm in t:
            return [t.replace(pm, "+", 1), t.replace(pm, "-", 1)]
    return [t]


def meaning(text: str, above: str = ""):
    """('equation', solutions, var) | ('chain', all_equal) | ('expression', expr) | None."""
    from sympy import S, solveset, Union, simplify
    t = text.strip().rstrip(".")
    for tail in ("=>", "⇒", "->", "="):
        if t.endswith(tail):                       # '(z+x)^4 =' : the expression the next line expands
            t = t[: -len(tail)].strip()
            break
    if t.startswith("=") and above:
        t = above.split("=")[-1] + t
    try:
        sides = t.split("=")
        if len(sides) == 1:
            return ("expression", _parse(t)) if "±" not in t else None
        if any(not s.strip() for s in sides):
            return None
        sols, var = None, None
        for v in _variants(t):
            exprs = [_parse(s) for s in v.split("=")]
            free = set().union(*(e.free_symbols for e in exprs))
            if not free:
                ok = all(simplify(e - exprs[0]) == 0 for e in exprs[1:])
                return ("chain", ok)
            if len(free) != 1 or len(exprs) != 2:
                return None
            (var,) = free
            s = solveset(exprs[0] - exprs[1], var, domain=S.Reals)
            sols = s if sols is None else Union(sols, s)
        return ("equation", sols, var)
    except Exception:
        return None


def check_steps(elements: list[Element]) -> dict[str, str]:
    """element id -> 'correct' | 'wrong' for every line sympy can decide."""
    from sympy import simplify, EmptySet
    steps = sorted((e for e in elements if e.kind in ("line", "formula") and e.legible),
                   key=lambda e: e.bbox[1])
    verdicts: dict[str, str] = {}
    task: dict[str, tuple] = {}         # group -> first equation / expression of the exercise
    above = ""
    for e in steps:
        m = meaning(e.text, above)
        above = e.text if not e.text.strip().startswith("=") else above.split("=")[0] + e.text
        if m is None:
            continue
        g = e.group
        if m[0] == "chain":
            verdicts[e.id] = "correct" if m[1] else "wrong"
            continue
        first = task.setdefault(g, m)
        if first is m or first[0] != m[0]:
            continue
        if m[0] == "equation":
            ok = m[1] != EmptySet and m[1].is_subset(first[1]) and m[2] == first[2]
        else:
            ok = simplify(m[1] - first[1]) == 0
        verdicts[e.id] = "correct" if ok else "wrong"
    return verdicts
