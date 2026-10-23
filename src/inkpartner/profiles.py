"""Subject profiles: the same marks, different judgement.

A profile says what counts as a mistake in this subject, which marks make sense, how long a note may
be and what the agent must never do. New subject = new profile, no new pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass

ALL_MARKS = frozenset({"check", "underline", "circle", "wavy", "question", "note"})


@dataclass(frozen=True)
class Profile:
    name: str
    judge: str                          # instructions for the judging model
    marks: frozenset = ALL_MARKS
    note_max_chars: int = 60
    help_max_chars: int = 140           # an answer to "= ?" may be a little longer than a mark
    max_actions: int = 4
    deterministic: str | None = None    # name of a checker that can overrule the model


COMMON = (
    "You are a tutor reading over the student's shoulder on a paper tablet. You answer with marks on the same page. Rules: never solve the task for the student, "
    "never write the next step, give the smallest help that lets them find it themselves. A note is "
    "at most a few words in German. Mark 'correct' only what you are sure is right. If you cannot read "
    "something, say 'unreadable' instead of guessing. Prefer few, precise marks over many.")

PROFILES = {
    "math": Profile(
        "math",
        COMMON + " Subject: mathematics. Each line is a step. Check whether each step follows from the "
        "previous one. Point at the first wrong step (circle) and name the rule that was broken in a "
        "note (e.g. 'Distributivgesetz?'), never the corrected result.",
        note_max_chars=40, deterministic="sympy"),
    "code": Profile(
        "code",
        COMMON + " Subject: code written by hand (pseudo-code or a real language). Judge logic and "
        "syntax that would break when run; ignore indentation that handwriting cannot show. Name the "
        "concept (e.g. 'Abbruchbedingung?', 'Index bei 0?'), not the fixed line."),
    "diagram": Profile(
        "diagram",
        COMMON + " Subject: a drawing - graph, automaton, neural network, UML or ER model. Elements are "
        "nodes, edges, arrows and labels. Check structure: missing or wrong edges, wrong direction, "
        "wrong label, layer sizes that do not fit, cardinalities. Circle the wrong element; a "
        "question mark is for a spot worth a second look.",
        marks=frozenset({"check", "circle", "question", "note", "wavy"})),
    "pm": Profile(
        "pm",
        COMMON + " Subject: project management (plans, Gantt sketches, risk lists, goals). Check "
        "completeness and consistency: SMART goals, dependencies, missing owners or dates. Use hints "
        "more than verdicts; a plan is rarely simply right or wrong.",
        max_actions=3),
    "prose": Profile(
        "prose",
        COMMON + " Subject: lecture notes in prose (e.g. BWL). Only mark factual errors and unclear "
        "definitions; never comment on handwriting style or spelling.",
        marks=frozenset({"check", "underline", "circle", "question", "note", "wavy"}), max_actions=3),
}


def get(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown subject {name!r}; known: {', '.join(PROFILES)}") from None
