"""A feedback plan: what the agent wants to say, checked by rules before any ink is drawn.

The model proposes actions; the rules below decide. The model never chooses colours - the verdict
does: correct = green, wrong = red, hint = blue, unreadable = gray. That keeps the colour semantics
from Notion (black = student, green = right, red = wrong) true no matter what the model writes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import layout, marks
from .elements import Element, page_asks_for_help

VERDICT_COLOR = {"correct": "green", "wrong": "red", "hint": "blue", "unreadable": "gray", "help": "blue"}
MARKS_FOR = {"correct": {"check", "underline"},
             "wrong": {"circle", "underline", "note"},
             "hint": {"question", "note"},
             "unreadable": {"wavy"},
             "help": {"note"}}


@dataclass
class Action:
    element: str
    verdict: str            # correct | wrong | hint | unreadable
    mark: str               # check | underline | circle | wavy | question | note
    text: str = ""          # only for notes
    why: str = ""           # for the log, never written on the page

    @property
    def color(self) -> str:
        return VERDICT_COLOR[self.verdict]

    def key(self, el: Element) -> str:
        return f"{el.fingerprint()}:{self.verdict}:{self.mark}"


@dataclass
class Review:
    accepted: list[Action] = field(default_factory=list)
    rejected: list[tuple[Action, str]] = field(default_factory=list)


def validate(actions: list[Action], elements: list[Element], profile, *, delivered: set[str] = frozenset(),
             overrides: dict[str, str] | None = None) -> Review:
    """Apply the interaction rules. `overrides` maps element id -> verdict from a deterministic
    checker (e.g. sympy); a model verdict that contradicts it is rejected."""
    by_id = {e.id: e for e in elements}
    overrides = overrides or {}
    asked = page_asks_for_help(elements)
    helpable = help_targets(elements)
    out = Review()
    for a in actions:
        el = by_id.get(a.element)
        reason = None
        if el is None:
            reason = "unknown element"
        elif el.kind == "printed":
            reason = "printed exercise text is never marked"
        elif a.verdict not in VERDICT_COLOR:
            reason = f"unknown verdict {a.verdict!r}"
        elif a.mark not in MARKS_FOR[a.verdict] or a.mark not in profile.marks:
            reason = f"mark {a.mark!r} not allowed for {a.verdict!r} in {profile.name}"
        elif a.verdict == "help" and not asked:
            reason = "nobody asked for help on this page"
        elif a.verdict == "help" and a.element not in helpable:
            reason = "help only where the question is (or the task right before it)"
        elif a.verdict == "correct" and not el.certain:
            reason = "uncertain reading is never confirmed green"
        elif a.verdict in ("correct", "wrong") and not el.legible:
            reason = "illegible element can only get a wavy line"
        elif el.id in overrides and a.verdict in ("correct", "wrong") and overrides[el.id] != a.verdict:
            reason = f"contradicts the deterministic check ({overrides[el.id]})"
        elif a.mark == "note" and not a.text.strip():
            reason = "empty note"
        elif a.mark == "note" and len(a.text) > (profile.help_max_chars if a.verdict == "help"
                                                   else profile.note_max_chars):
            reason = "note too long"
        elif a.key(el) in delivered:
            reason = "already on the page"
        if reason:
            out.rejected.append((a, reason))
        else:
            out.accepted.append(a)
    # Small and incremental beats one big throw: at most N actions per round, errors first.
    order = {"help": 0, "wrong": 1, "unreadable": 2, "hint": 3, "correct": 4}
    out.accepted.sort(key=lambda a: order[a.verdict])
    helps = [a for a in out.accepted if a.verdict == "help"]
    for a in helps[1:]:                                # one answer to one question per round
        out.accepted.remove(a)
        out.rejected.append((a, "only one help note per round"))
    for a in out.accepted[profile.max_actions:]:
        out.rejected.append((a, "over the per-round limit"))
    out.accepted = out.accepted[:profile.max_actions]
    return out


def help_targets(elements: list[Element]) -> set[str]:
    """The element that asks, and the nearest element above it (the task the question is about).
    Real page 2026-10-23: 'das macht mir Probleme' made the agent hang help on five lines."""
    from .elements import ASK
    out = set()
    for q in elements:
        if not ASK.search(q.text or ""):
            continue
        out.add(q.id)
        above = [e for e in elements if e.id != q.id and e.bbox[1] <= q.bbox[1] + 0.5 * (q.bbox[3] - q.bbox[1])
                 and not ASK.search(e.text or "")]
        if above:
            qc = ((q.bbox[0] + q.bbox[2]) / 2, (q.bbox[1] + q.bbox[3]) / 2)
            near = min(above, key=lambda e: abs((e.bbox[1] + e.bbox[3]) / 2 - qc[1])
                       + 0.3 * abs((e.bbox[0] + e.bbox[2]) / 2 - qc[0]))
            out.add(near.id)
    return out


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
