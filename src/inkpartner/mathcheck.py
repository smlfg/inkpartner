"""Deterministic step check for algebra: does each line keep the solution set of the line before?

The model is good at reading and at explaining, unreliable at deciding whether 3x+2=15 follows from
3(x+2)=15 (device test 2026-10-20: right place, wrong reason). Where sympy can decide, sympy decides
and the model's verdict must agree. Where sympy cannot parse a line, there is no override.
"""
from __future__ import annotations

import re

from .elements import Element


def _parse(side: str):
    from sympy.parsing.sympy_parser import (parse_expr, standard_transformations,
                                            implicit_multiplication_application, convert_xor)
    s = side.replace("·", "*").replace("×", "*").replace("−", "-").replace(":", "/").replace(",", ".")
    s = re.sub(r"\s+", "", s)
    if not s:
        raise ValueError("empty")
    return parse_expr(s, transformations=standard_transformations
                      + (implicit_multiplication_application, convert_xor))


def meaning(text: str):
    """('equation', solution set) | ('expression', expr) | None when it cannot be parsed."""
    from sympy import S, solveset
    t = text.strip().rstrip(".")
    try:
        if t.count("=") == 1:
            left, right = (_parse(p) for p in t.split("="))
            free = (left - right).free_symbols
            if len(free) != 1:
                return None
            (var,) = free
            return ("equation", solveset(left - right, var, domain=S.Reals))
        if "=" not in t:
            return ("expression", _parse(t))
    except Exception:
        return None
    return None


def check_steps(elements: list[Element]) -> dict[str, str]:
    """element id -> 'correct' | 'wrong' for every step sympy can compare with the step before."""
    from sympy import simplify
    steps = [e for e in elements if e.kind in ("line", "formula") and e.legible]
    steps.sort(key=lambda e: e.bbox[1])
    verdicts, prev = {}, None
    for e in steps:
        m = meaning(e.text)
        if m is None:
            prev = None
            continue
        if prev is not None and prev[0] == m[0]:
            if m[0] == "equation":
                same = prev[1] == m[1]
            else:
                same = simplify(prev[1] - m[1]) == 0
            verdicts[e.id] = "correct" if same else "wrong"
        # Each step is judged against the step right before it, like a teacher marks a follow-on
        # error ("Folgefehler"): the wrong step is red once, correct work after it stays correct.
        prev = m
    return verdicts
