"""One review round: read -> check -> judge -> rules -> ink. Pure orchestration, no I/O to the tablet."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import mathcheck, plan, profiles, speech
from .elements import Element
from .page import PAGE_W, PAGE_H


@dataclass
class Round:
    subject: str
    elements: list[Element]
    accepted: list[plan.Action]
    rejected: list[tuple[plan.Action, str]]
    strokes: list[dict]
    speech: dict[str, str] = field(default_factory=dict)   # action key -> sentence (only speakable ones)
    checked: dict[str, str] = field(default_factory=dict)


def run(strokes: list[dict], *, model=None, subject: str | None = None, elements: list[Element] | None = None,
        proposals: list[tuple[plan.Action, str]] | None = None, delivered: set[str] = frozenset(),
        reader=None, judge_model=None) -> Round:
    """`elements` / `proposals` can be given (tests, replays); otherwise the model provides them.
    `reader` (readers.get) replaces the default reading; `judge_model` judges instead of `model`."""
    from . import agent
    if elements is None:
        guessed, elements = reader(strokes) if reader else agent.read(model, strokes)
        subject = subject or guessed
    subject = subject or "math"
    profile = profiles.get(subject)
    checked = mathcheck.check_steps(elements) if profile.deterministic == "sympy" else {}
    if proposals is None:
        proposals = agent.judge(judge_model or model, strokes, elements, profile, checked=checked)
    # What the checker proved correct gets its check mark even if the model forgot it -
    # "bis hierhin fehlerfrei" should not depend on the model's mood.
    acted = {a.element for a, _ in proposals}
    proposals = list(proposals) + [(plan.Action(eid, "correct", "check", why="sympy"), "")
                                   for eid, v in checked.items() if v == "correct" and eid not in acted]
    review = plan.validate([a for a, _ in proposals], elements, profile, delivered=delivered, overrides=checked)
    height = max([PAGE_H] + [int(p[1]) + 200 for s in strokes for p in s["points"]])
    ink = plan.draw(review.accepted, elements, strokes, width=PAGE_W, height=height)
    by_id = {e.id: e for e in elements}
    said = {a.key(by_id[a.element]): s for a, s in proposals
            if a in review.accepted and speech.speakable(s)}
    return Round(subject, elements, review.accepted, review.rejected, ink, said, checked)
