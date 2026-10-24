"""One review round: read -> check -> judge -> rules -> ink. Pure orchestration, no I/O to the tablet."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import mathcheck, plan, profiles, speech, tutor
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
    tutor: dict[str, dict] = field(default_factory=dict)   # action key -> the help ladder's answer


def run(strokes: list[dict], *, model=None, subject: str | None = None, elements: list[Element] | None = None,
        proposals: list[tuple[plan.Action, str]] | None = None, delivered: set[str] = frozenset(),
        reader=None, judge_model=None, tutor_model=None, help_levels: dict | None = None,
        background=None) -> Round:
    """`elements` / `proposals` can be given (tests, replays); otherwise the model provides them.
    `reader` (readers.get) replaces the default reading; `judge_model` judges instead of `model`.
    With `tutor_model` and `help_levels` (task -> how often help was given) a help request is answered
    by the help ladder (tutor.py): a level-aware note and spoken sentences."""
    from . import agent
    if elements is None:
        from .geometry import snap
        if reader:      # readers without a background parameter keep working on plain pages
            guessed, elements = reader(strokes, background=background) if background is not None else reader(strokes)
        else:
            guessed, elements = agent.read(model, strokes, background)
        elements = snap(elements, strokes)           # marks land on the real ink, not the model's guess
        subject = subject or guessed
    subject = subject or "math"
    profile = profiles.get(subject)
    checked = mathcheck.check_steps(elements) if profile.deterministic == "sympy" else {}
    if proposals is None:
        proposals = agent.judge(judge_model or model, strokes, elements, profile, checked=checked,
                                background=background)
    # What the checker proved correct gets its check mark even if the model forgot it -
    # "bis hierhin fehlerfrei" should not depend on the model's mood.
    # The same for a step the checker proved wrong: the red circle does not depend on the model either.
    acted = {a.element for a, _ in proposals}
    marked_wrong = {a.element for a, _ in proposals if a.verdict == "wrong"}
    proposals = list(proposals) + [(plan.Action(eid, "correct", "check", why="sympy"), "")
                                   for eid, v in checked.items() if v == "correct" and eid not in acted]
    # Only the FIRST wrong step of an exercise gets the automatic circle: lines built on it are wrong
    # too, but a teacher marks the cause once, not every follow-on line (they still never turn green).
    by_id = {e.id: e for e in elements}
    first_wrong = {}
    for eid, v in checked.items():                 # insertion order = top to bottom
        if v == "wrong":
            first_wrong.setdefault(by_id[eid].group, eid)
    proposals += [(plan.Action(eid, "wrong", "circle", why="sympy"), "")
                  for eid in first_wrong.values() if eid not in marked_wrong]
    # An element nobody can read gets the wavy line - the reading decided that, not the judge's mood.
    acted = {a.element for a, _ in proposals}
    proposals += [(plan.Action(e.id, "unreadable", "wavy", why="illegible"), "")
                  for e in elements if not e.legible and e.id not in acted and profile.marks >= {"wavy"}]
    review = plan.validate([a for a, _ in proposals], elements, profile, delivered=delivered, overrides=checked)
    taught = _teach(review.accepted, elements, subject, profile, tutor_model, help_levels)
    height = max([PAGE_H] + [int(p[1]) + 200 for s in strokes for p in s["points"]])
    ink = plan.draw(review.accepted, elements, strokes, width=PAGE_W, height=height)
    by_id = {e.id: e for e in elements}
    said = {a.key(by_id[a.element]): s for a, s in proposals
            if a in review.accepted and speech.speakable(s)}
    for k, out in taught.items():
        said[k] = " ".join(tutor.say_ok(out["speech"]))   # the ladder's sentences replace the one-liner
    return Round(subject, elements, review.accepted, review.rejected, ink, said, checked, taught)


SUBJECT_DE = {"math": "Mathematik", "code": "Programmieren", "diagram": "Informatik (Diagramme, Graphen, "
              "neuronale Netze)", "pm": "Projektmanagement", "prose": "BWL"}


def _teach(accepted, elements, subject, profile, model, levels) -> dict[str, dict]:
    if model is None or levels is None:
        return {}
    out = {}
    order = [e.id for e in elements]
    by_id = {e.id: e for e in elements}
    for a in accepted:
        if a.verdict != "help":
            continue
        el = by_id[a.element]
        task = el.text
        i = order.index(el.id)
        if not re.search(r"[0-9=^()+*/]", task) and i > 0:      # "wie geht das?" - the task is the line before
            task = f"{by_id[order[i - 1]].text}   {task}"
        key = tutor.task_key(task)
        level = levels.get(key, 0) + 1
        student = " | ".join(e.text for e in elements if e.group == el.group and e.id != el.id and e.text)
        try:
            ans = tutor.explain(model, task, student, level=level, subject=SUBJECT_DE.get(subject, subject))
        except Exception:                          # the judge's own note stays; no speech
            continue
        levels[key] = level
        note = ans["note"][:profile.help_max_chars]
        if level == 3 and ans["probe"]:
            note = f"{note} Neu: {ans['probe']}" if note else f"Neu: {ans['probe']}"
        if note:
            a.text = note
        out[a.key(el)] = ans
    return out
