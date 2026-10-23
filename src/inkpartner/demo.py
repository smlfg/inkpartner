"""A page you can look at without a tablet and without a model: every mark, three subjects.

The student's writing is simulated with a single-stroke font in black, slightly slanted downhill
the way Samuel writes. Elements and verdicts are given by hand - this shows the vocabulary and the
layout, not the reading or the judging.
"""
from __future__ import annotations

from . import marks, review
from .elements import Element
from .plan import Action


def _write(s, x, y, h=48, slant=0.04):
    ink = marks.text(s, (x, y), height=h, color="black")
    for st in ink:
        st["author"] = "user"
        for p in st["points"]:
            p[1] += (p[0] - x) * slant
    return ink


def _line(s, x, y, eid, kind="line", **kw):
    ink = _write(s, x, y)
    return ink, Element(id=eid, kind=kind, bbox=marks.bbox_of(ink), text=s,
                        confidence=kw.get("confidence", 0.95), legible=kw.get("legible", True))


def page():
    strokes, els = [], []
    rows = [("3(x+2)=15", "m1", {}), ("3x+2=15", "m2", {}), ("3x=13", "m3", {}),
            ("x=13/3", "m4", {"confidence": 0.5})]
    y = 140
    for text, eid, kw in rows:
        ink, el = _line(text, 120, y, eid, **kw)
        strokes += ink
        els.append(el)
        y += 110
    ink, el = _line("for i in range(1, n):", 120, 700, "c1", "code")
    strokes += ink
    els.append(el)
    ink, el = _line("  s = s + a[i]", 120, 790, "c2", "code")
    strokes += ink
    els.append(el)
    # a tiny neural network drawing: 2 inputs -> 1 output, one edge missing
    nodes = {"n1": (260, 1150), "n2": (260, 1330), "n3": (620, 1240)}
    for nid, (cx, cy) in nodes.items():
        ring = marks.circle([cx - 30, cy - 30, cx + 30, cy + 30], color="black")
        for st in ring:
            st["author"] = "user"
        strokes += ring
        els.append(Element(id=nid, kind="node", bbox=[cx - 44, cy - 42, cx + 44, cy + 42],
                           text=nid, confidence=0.9))
    edge = [{"points": [[304, 1160, .7], [576, 1232, .7]], "color": "black", "width": 3, "author": "user"}]
    strokes += edge
    els.append(Element(id="w1", kind="edge", bbox=marks.bbox_of(edge), text="n1->n3", confidence=0.9))
    ink, el = _line("~#%&", 120, 1500, "u1", legible=False, confidence=0.1)
    strokes += ink
    els.append(el)
    return strokes, els


def proposals():
    A = Action
    return [
        (A("m1", "correct", "check"), ""),
        (A("m2", "wrong", "circle"), ""),
        (A("m2", "wrong", "note", text="Distributivgesetz?"), "Schau dir noch mal an, wie du die Klammer aufgelöst hast."),
        (A("m4", "correct", "check"), ""),                 # rejected: reading is uncertain
        (A("c1", "wrong", "note", text="Index bei 0?"), "Fängt die Liste wirklich bei eins an?"),
        (A("n2", "hint", "question"), ""),
        (A("n2", "wrong", "note", text="Kante fehlt"), ""),
        (A("u1", "unreadable", "wavy"), ""),
    ]


def build():
    strokes, els = page()
    by_subject = {"math": ["m1", "m2", "m3", "m4"], "code": ["c1", "c2"], "diagram": ["n1", "n2", "n3", "w1", "u1"]}
    ink, log = [], []
    for subject, ids in by_subject.items():
        sub = [e for e in els if e.id in ids]
        props = [p for p in proposals() if p[0].element in ids]
        r = review.run(strokes + ink, subject=subject, elements=sub, proposals=props)
        ink += r.strokes
        log.append(r)
    return strokes, ink, log
