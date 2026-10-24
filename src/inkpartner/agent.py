"""The two model calls: read the page into elements, then judge them into actions.

Reading follows algebra-agent's decision of 2026-10-21 (variant B): the whole page goes to the model
as one image and the model returns the elements with their boxes - no geometric line cutting first
("viel Skizze ist der Text-Erkennung Gift"). Judging gets the image again plus the elements, so a
note about a drawing can refer to what it looks like.
"""
from __future__ import annotations

import json

from . import page as pagemod
from .elements import KINDS, Element
from .plan import Action

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "enum": ["math", "code", "diagram", "pm", "prose"]},
        "elements": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(KINDS)},
                "text": {"type": "string"},
                "latex": {"type": "string"},
                "box": {"type": "array", "items": {"type": "number"}},
                "confidence": {"type": "number"},
                "legible": {"type": "boolean"},
                "group": {"type": "string"},
            },
            "required": ["kind", "text", "latex", "box", "confidence", "legible", "group"],
            "additionalProperties": False}},
    },
    "required": ["subject", "elements"],
    "additionalProperties": False,
}

READ_PROMPT = (
    "This is a page of handwriting from a paper tablet. List every element on it in reading order: "
    "lines of text or math, lines of code, and for drawings the nodes, edges, arrows, boxes and labels. "
    "For each element give: kind; text exactly as written, even if it is wrong (math as plain text with "
    "^ for powers, sqrt() for roots, ± where written, e.g. 3(x+2)=15); latex for formulas, else empty; box = [x0, y0, x1, y1] as fractions "
    "0..1 of the image width and height; confidence 0..1 in your reading; legible=false if you cannot "
    "read it - never guess; group = the exercise the element belongs to (its number or label, e.g. "
    "'4b'; the same value for all lines of one exercise, a new value where a new exercise starts). Also say which subject the page is: math, code, diagram, pm or prose.")

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"actions": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "element": {"type": "string"},
            "verdict": {"type": "string", "enum": ["correct", "wrong", "hint", "unreadable", "help"]},
            "mark": {"type": "string", "enum": ["check", "underline", "circle", "wavy", "question", "note"]},
            "text": {"type": "string"},
            "why": {"type": "string"},
            "speech": {"type": "string"},
        },
        "required": ["element", "verdict", "mark", "text", "why", "speech"],
        "additionalProperties": False}}},
    "required": ["actions"],
    "additionalProperties": False,
}


PRINTED = (" Printed text (an exercise sheet under the handwriting, thin and regular) is the task, not the "
           "student's work: list each printed line as kind 'printed' with its text, and give the handwritten "
           "answer lines the same group as the printed exercise they answer.")


def read(model, strokes: list[dict], background=None) -> tuple[str, list[Element]]:
    """Student strokes -> (subject, elements). Agent ink is left out of the picture on purpose.
    `background`: the printed page (PDF) under the ink - then the exercise text is read too."""
    img = pagemod.render(strokes, authors=("user",), background=background)
    fx0, fy0, fx1, fy1 = img.info["frame"]       # the image covers this part of the page
    data = model.json([pagemod.png_bytes(img)], READ_PROMPT + (PRINTED if background is not None else ""),
                      READ_SCHEMA)
    els = []
    for i, d in enumerate(data["elements"]):
        b = (d["box"] + [0, 0, 0, 0])[:4]
        bbox = [fx0 + b[0] * (fx1 - fx0), fy0 + b[1] * (fy1 - fy0),
                fx0 + b[2] * (fx1 - fx0), fy0 + b[3] * (fy1 - fy0)]
        bbox = [min(bbox[0], bbox[2]), min(bbox[1], bbox[3]), max(bbox[0], bbox[2]), max(bbox[1], bbox[3])]
        els.append(Element(id=f"e{i}", kind=d["kind"], bbox=bbox, text=d["text"], latex=d["latex"],
                           confidence=float(d["confidence"]), legible=bool(d["legible"]),
                           group=d.get("group", "")))
    return data["subject"], els


def judge(model, strokes: list[dict], elements: list[Element], profile, *,
          checked: dict[str, str] | None = None, background=None) -> list[tuple[Action, str]]:
    """Elements -> proposed actions (with optional speech). The rules in plan.validate decide."""
    listing = json.dumps([{"id": e.id, "kind": e.kind, "text": e.text, "legible": e.legible,
                           "confidence": round(e.confidence, 2), "asks_for_help": asks_for_help(e)}
                          for e in elements], ensure_ascii=False)
    facts = ""
    if checked:
        facts = ("\nA symbolic checker already decided these steps; agree with it: "
                 + json.dumps(checked) + "\n")
    prompt = (f"{profile.judge}\n\nElements on the page:\n{listing}\n{facts}\n"
              "Propose at most a few actions. Marks: check/underline for correct; circle, underline or a "
              "note for wrong; question or note for a hint; wavy for unreadable. If the student asks for "
              "help (asks_for_help, a question mark, '= ?', 'Hilfe', a task with no own work yet), answer "
              "with verdict 'help', mark 'note': say in German what the problem is and the very next step "
              f"or the rule to use, at most {profile.help_max_chars} characters, never the result. "
              "'text' is the note (empty unless mark=note). 'speech' is one short German sentence of natural language that "
              "could be said aloud instead - no formulas, symbols, code or file paths; empty if nothing "
              "worth saying."
              + (" Elements of kind 'printed' are the exercise sheet: never mark them, judge the handwritten "
                 "answers against them." if any(e.kind == "printed" for e in elements) else ""))
    img = pagemod.render(strokes, authors=("user", "agent"), background=background)
    data = model.json([pagemod.png_bytes(img)], prompt, JUDGE_SCHEMA)
    return [(Action(element=a["element"], verdict=a["verdict"], mark=a["mark"], text=a["text"], why=a["why"]),
             a["speech"]) for a in data["actions"]]


def asks_for_help(e: Element) -> bool:
    """A line with a question - '(3x+4y)^3 = ?' - is a request, not an answer to check."""
    from .elements import ASK
    return bool(ASK.search(e.text or ""))
