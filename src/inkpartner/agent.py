"""The two model calls: read the page into elements, then judge them into actions.

Reading follows algebra-agent's decision of 2026-10-21 (variant B): the whole page goes to the model
as one image and the model returns the elements with their boxes - no geometric line cutting first
("viel Skizze ist der Text-Erkennung Gift"). Judging gets the image again plus the elements, so a
note about a drawing can refer to what it looks like.
"""
from __future__ import annotations

import base64
import json

from . import page as pagemod
from .elements import KINDS, Element
from .plan import Action

MODEL = "claude-opus-5-5"

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
            },
            "required": ["kind", "text", "latex", "box", "confidence", "legible"],
            "additionalProperties": False}},
    },
    "required": ["subject", "elements"],
    "additionalProperties": False,
}

READ_PROMPT = (
    "This is a page of handwriting from a paper tablet. List every element on it in reading order: "
    "lines of text or math, lines of code, and for drawings the nodes, edges, arrows, boxes and labels. "
    "For each element give: kind; text exactly as written, even if it is wrong (math as plain text with "
    "^ for powers, e.g. 3(x+2)=15); latex for formulas, else empty; box = [x0, y0, x1, y1] as fractions "
    "0..1 of the image width and height; confidence 0..1 in your reading; legible=false if you cannot "
    "read it - never guess. Also say which subject the page is: math, code, diagram, pm or prose.")

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"actions": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "element": {"type": "string"},
            "verdict": {"type": "string", "enum": ["correct", "wrong", "hint", "unreadable"]},
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


def _image_block(png: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.standard_b64encode(png).decode()}}


def _json_call(client, content, schema, effort: str) -> dict:
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined the request")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("model output was cut off")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def read(client, strokes: list[dict], *, effort: str = "high") -> tuple[str, list[Element]]:
    """Student strokes -> (subject, elements). Agent ink is left out of the picture on purpose."""
    img = pagemod.render(strokes, authors=("user",))
    fx0, fy0, fx1, fy1 = img.info["frame"]       # the image covers this part of the page
    data = _json_call(client, [_image_block(pagemod.png_bytes(img)), {"type": "text", "text": READ_PROMPT}],
                      READ_SCHEMA, effort)
    els = []
    for i, d in enumerate(data["elements"]):
        b = (d["box"] + [0, 0, 0, 0])[:4]
        bbox = [fx0 + b[0] * (fx1 - fx0), fy0 + b[1] * (fy1 - fy0),
                fx0 + b[2] * (fx1 - fx0), fy0 + b[3] * (fy1 - fy0)]
        bbox = [min(bbox[0], bbox[2]), min(bbox[1], bbox[3]), max(bbox[0], bbox[2]), max(bbox[1], bbox[3])]
        els.append(Element(id=f"e{i}", kind=d["kind"], bbox=bbox, text=d["text"], latex=d["latex"],
                           confidence=float(d["confidence"]), legible=bool(d["legible"])))
    return data["subject"], els


def judge(client, strokes: list[dict], elements: list[Element], profile, *,
          checked: dict[str, str] | None = None, effort: str = "high") -> list[tuple[Action, str]]:
    """Elements -> proposed actions (with optional speech). The rules in plan.validate decide."""
    listing = json.dumps([{"id": e.id, "kind": e.kind, "text": e.text, "legible": e.legible,
                           "confidence": round(e.confidence, 2)} for e in elements], ensure_ascii=False)
    facts = ""
    if checked:
        facts = ("\nA symbolic checker already decided these steps; agree with it: "
                 + json.dumps(checked) + "\n")
    prompt = (f"{profile.judge}\n\nElements on the page:\n{listing}\n{facts}\n"
              "Propose at most a few actions. Marks: check/underline for correct; circle, underline or a "
              "note for wrong; question or note for a hint; wavy for unreadable. 'text' is the note "
              "(empty unless mark=note). 'speech' is one short German sentence of natural language that "
              "could be said aloud instead - no formulas, symbols, code or file paths; empty if nothing "
              "worth saying.")
    img = pagemod.render(strokes, authors=("user", "agent"))
    data = _json_call(client, [_image_block(pagemod.png_bytes(img)), {"type": "text", "text": prompt}],
                      JUDGE_SCHEMA, effort)
    return [(Action(element=a["element"], verdict=a["verdict"], mark=a["mark"], text=a["text"], why=a["why"]),
             a["speech"]) for a in data["actions"]]
