"""The contract between reading and judging: a page is a list of elements.

An element is whatever the agent can point at - a line of algebra, a line of code, a node of a
graph, an arrow, a box in a project plan. Every subject uses the same contract, so the feedback
vocabulary (marks.py) works for all of them. Coordinates are page pixels (Paper Pro: 1620 wide,
origin top-left, y grows downward).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import json

KINDS = ("line", "formula", "code", "text", "node", "edge", "arrow", "box", "table", "drawing")


@dataclass
class Element:
    id: str
    kind: str
    bbox: list[float]                 # [x0, y0, x1, y1] in page pixels
    text: str = ""                    # what is written, as plain text ("" for a pure drawing)
    latex: str = ""                   # for formulas, when the reader could give it
    confidence: float = 0.0           # 0..1, the reader's own certainty
    legible: bool = True              # False: the reader could not read it - never green
    group: str = ""                   # the exercise it belongs to ("4b"); math checks within a group
    stroke_ids: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown element kind {self.kind!r}")
        x0, y0, x1, y1 = (float(v) for v in self.bbox)
        if x1 < x0 or y1 < y0:
            raise ValueError(f"element {self.id}: bbox {self.bbox} is inverted")
        self.bbox = [x0, y0, x1, y1]

    @property
    def certain(self) -> bool:
        """Only a certain reading may ever be confirmed (green)."""
        return self.legible and self.confidence >= 0.8

    def fingerprint(self) -> str:
        """Identifies the content of the element: same text, same place -> same feedback."""
        key = json.dumps([self.kind, self.text.strip(), [round(v / 20) for v in self.bbox]])
        return hashlib.sha1(key.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return asdict(self)


def from_dicts(items: list[dict]) -> list[Element]:
    return [Element(**{k: v for k, v in d.items() if k in Element.__dataclass_fields__}) for d in items]
