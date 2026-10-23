"""Simulated student, simulated tablet, real agent: does it react, and how?

The student writes a scenario line by line in a handwriting-like single-stroke script (jitter,
slant downhill like Samuel's, varying size, raised exponents). After each line the real Watcher runs
against a simulated tablet: it notices the change, waits for the pen pause, reads, checks, judges,
and "writes" its marks into the agent layer of the simulated page. Each reaction is scored against
the scenario's truth:

    wrong line       hit = a 'wrong' mark on it; a 'correct' mark is a CRITICAL error (false green)
    correct line     a 'wrong' mark is CRITICAL (false red); a check or nothing is fine
    help request     hit = a 'help' note (or at least a hint)
    unreadable       hit = a wavy line; a 'correct' mark is CRITICAL

Nothing here touches the real tablet.
"""
from __future__ import annotations

import difflib
import json
import math
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import marks, models, page as pagemod, readers
from .guards import Guard, Limits


# ------------------------------------------------------------------ scenarios
@dataclass
class Line:
    text: str
    expect: str            # wrong | ok | help | unreadable


@dataclass
class Scenario:
    name: str
    subject: str
    lines: list[Line]


SCENARIOS = [
    Scenario("distributiv-fehler", "math", [Line("3(x+2)=15", "ok"), Line("3x+2=15", "wrong")]),
    Scenario("lineare-gleichung-richtig", "math", [Line("2x+4=10", "ok"), Line("2x=6", "ok"), Line("x=3", "ok")]),
    Scenario("hilfe-binom-hoch-3", "math", [Line("(3x+4y)^3 = ?", "help")]),
    Scenario("binom-hoch-4-falsch", "math", [Line("(z+x)^4 =", "ok"), Line("z^4+zx^4+z^4x+x^4", "wrong")]),
    Scenario("quadratische-ergaenzung", "math", [Line("x^2+6x=7", "ok"), Line("(x+3)^2=16", "ok"),
                                                 Line("x+3=5", "wrong")]),
    Scenario("gekritzel", "math", [Line("2x=8", "ok"), Line("~", "unreadable")]),
]


# --------------------------------------------------------------- handwriting
def _segments(text: str):
    """'(3x+4y)^3 = ?' -> [('(3x+4y)', False), ('3', True), (' = ?', False)]"""
    out, i = [], 0
    for m in re.finditer(r"\^(\([^)]*\)|[A-Za-z0-9]+)", text):
        out.append((text[i:m.start()], False))
        out.append((m.group(1).strip("()"), True))
        i = m.end()
    out.append((text[i:], False))
    return [(t, sup) for t, sup in out if t]


def handwrite(text: str, origin, height: float, rng: random.Random, *, slant_deg=3.0, color="black"):
    """Single-stroke script with the irregularities of real handwriting."""
    if text == "~":                                   # a scribble nobody can read
        x0, y0 = origin
        pts = [[x0 + i * 6, y0 + height / 2 + rng.uniform(-height / 2, height / 2), .6] for i in range(40)]
        return [{"points": pts, "color": color, "width": 3, "author": "user"}]
    x, y = origin
    ink = []
    for seg, sup in _segments(text):
        h = height * (0.55 if sup else 1.0)
        yy = y - height * 0.35 if sup else y
        part = marks.text(seg, (x, yy), height=h, color=color)
        x += marks.text_size(seg, h)[0] + h * 0.15
        ink += part
    x0 = origin[0]
    phase, wob = rng.uniform(0, 6.28), rng.uniform(0.01, 0.03) * height
    tan = math.tan(math.radians(slant_deg))
    for s in ink:
        s["author"], s["width"] = "user", 3
        for p in s["points"]:
            dx = p[0] - x0
            p[0] += (origin[1] + height - p[1]) * 0.12 + rng.gauss(0, height * 0.012)      # italic shear
            p[1] += dx * tan + wob * math.sin(dx / (height * 1.7) + phase) + rng.gauss(0, height * 0.012)
            p[2] = round(rng.uniform(0.45, 0.85), 2)
    return ink


# ------------------------------------------------------------- sim tablet
class SimTablet:
    """One page file, a clock, and the same interface the Watcher uses for the real tablet."""

    REL = "sim-doc/sim-page.rm"

    def __init__(self, workdir: str):
        self.dir = workdir
        self.path = os.path.join(workdir, "page.rm")
        pagemod.new_page(self.path)
        self.clock = 1_000_000
        self.mtime = 0
        self.host = "sim"
        self.guard = Guard(os.path.join(workdir, "STOP"), Limits(), log=lambda *a: None)
        self.monitor = None
        self.allow_restart = False

    def _append(self, strokes, layer):
        tmp = self.path + ".new"
        pagemod.append_strokes(self.path, strokes, tmp, layer=layer)
        os.replace(tmp, self.path)
        self.mtime = self.clock

    def student_writes(self, strokes):
        self._append(strokes, "Layer 1")

    def scan(self):
        return {self.REL: (self.mtime, os.path.getsize(self.path))}

    def fetch(self, rel):
        return Path(self.path).read_bytes()

    def name(self, rel):
        return "Simulation"

    def strokes(self):
        return pagemod.read_strokes(self.path)


class SimPen:
    """A perfect pen: the agent's marks land exactly where planned (transport is tested elsewhere)."""

    def __init__(self, tablet: SimTablet):
        self.tablet = tablet

    def deliver(self, strokes, rel):
        self.tablet._append(strokes, pagemod.AGENT_LAYER)
        return {"status": "sim"}


# ------------------------------------------------------------------ scoring
def _norm(t: str) -> str:
    t = t.lower().replace("·", "*").replace("×", "*").replace("²", "^2").replace("³", "^3").replace("⁴", "^4")
    return re.sub(r"[\s*]", "", t)


def _overlap(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1.0, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / area


@dataclass
class LineResult:
    text: str
    expect: str
    read_as: str
    read_score: float
    verdicts: list[str]
    outcome: str           # hit | miss | ok | critical | partial


def score_line(line: Line, box, elements, rounds) -> LineResult:
    """`elements`: the last reading; `rounds`: [(elements, accepted actions)] of every review round -
    element ids are per round, so marks are mapped to lines through that round's boxes."""
    best, best_el = 0.0, None
    for e in elements:
        r = difflib.SequenceMatcher(None, _norm(line.text), _norm(e.text)).ratio()
        if _overlap(box, e.bbox) > 0 or _overlap(e.bbox, box) > 0:
            r += 0.001                                 # prefer the element at the right place
        if r > best:
            best, best_el = r, e
    found = set()
    for els, acts in rounds:
        ids = {e.id for e in els if _overlap(box, e.bbox) > 0.15 or _overlap(e.bbox, box) > 0.15}
        found |= {a.verdict for a in acts if a.element in ids}
    verdicts = sorted(found)
    v = set(verdicts)
    if line.expect == "wrong":
        outcome = "critical" if "correct" in v else "hit" if "wrong" in v else "partial" if v & {"hint", "help"} else "miss"
    elif line.expect == "ok":
        outcome = "critical" if "wrong" in v else "ok"
    elif line.expect == "help":
        outcome = "hit" if "help" in v else "partial" if "hint" in v else "miss"
    else:
        outcome = "critical" if "correct" in v else "hit" if "unreadable" in v else "miss"
    return LineResult(line.text, line.expect, best_el.text if best_el else "", round(min(best, 1.0), 2),
                      verdicts, outcome)


# --------------------------------------------------------------------- loop
@dataclass
class Run:
    config: str
    scenario: str
    lines: list = field(default_factory=list)
    rounds: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    preview: str = ""


def run_scenario(sc: Scenario, reader_spec: str, judge_spec: str, out_dir: str, seed: int = 7, log=print) -> Run:
    from .watch import Watcher
    rng = random.Random(seed)
    work = tempfile.mkdtemp(prefix="inkp-sim-")
    tab = SimTablet(work)
    reader = readers.get(reader_spec)
    judge = models.get(judge_spec)
    w = Watcher(tab, judge, subject=sc.subject, pen=SimPen(tab), log=lambda *a: None, reader=reader,
                judge_model=judge, state_file=os.path.join(work, "state.json"))
    w.verify_wait_s, w.verify_tries = 0, 1
    run = Run(f"{reader_spec} | judge {judge_spec}", sc.name)
    w.tick()                                           # the empty page is old news
    y = 220.0
    boxes, judged = [], []
    for i, line in enumerate(sc.lines):
        height = rng.uniform(70, 95)
        tab.clock += 30
        ink = handwrite(line.text, (200 + rng.uniform(-30, 30), y), height, rng)
        tab.student_writes(ink)
        boxes.append(marks.bbox_of(ink))
        tab.clock += 1
        assert w.tick() is None                        # still writing: no reaction yet
        tab.clock += int(w.settle_s) + 2
        t0 = time.time()
        try:
            r = w.tick()
        except Exception as e:                         # a model error is a result, not a crash
            run.errors.append(f"line {i}: {e}")
            log(f"    error: {e}")
            r = None
        dt = round(time.time() - t0, 1)
        if r is not None:
            judged.append((r.elements, r.accepted))
            run.rounds.append({"after_line": i, "seconds": dt, "subject": r.subject,
                               "read": [e.text for e in r.elements],
                               "marks": [f"{a.verdict}/{a.mark} {a.element} {a.text}".strip() for a in r.accepted],
                               "rejected": [f"{a.verdict}/{a.mark} {a.element}: {why}" for a, why in r.rejected]})
            log(f"    after line {i + 1} ({dt}s): read {[e.text for e in r.elements]} -> "
                f"{[f'{a.verdict}/{a.mark}' for a in r.accepted]}")
        all_ink = tab.strokes()
        y = max(p[1] for s in all_ink for p in s["points"]) + 90
    last = getattr(w, "last_round", None)
    elements = last.elements if last else []
    for line, box in zip(sc.lines, boxes):
        run.lines.append(asdict(score_line(line, box, elements, judged)))
    os.makedirs(out_dir, exist_ok=True)
    run.preview = os.path.join(out_dir, f"{_slug(run.config)}__{sc.name}.png")
    pagemod.render(tab.strokes(), scale=0.4).save(run.preview)
    return run


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", s).strip("-")[:80]


def summarize(runs: list[Run]) -> dict:
    by = {}
    for r in runs:
        c = by.setdefault(r.config, {"lines": 0, "hit": 0, "critical": 0, "miss": 0, "partial": 0, "ok": 0,
                                     "read": [], "seconds": [], "errors": 0})
        for l in r.lines:
            c["lines"] += 1
            c[l["outcome"]] += 1
            c["read"].append(l["read_score"])
        c["seconds"] += [x["seconds"] for x in r.rounds]
        c["errors"] += len(r.errors)
    for c in by.values():
        c["read_mean"] = round(sum(c["read"]) / max(1, len(c["read"])), 2)
        c["seconds_mean"] = round(sum(c["seconds"]) / max(1, len(c["seconds"])), 1)
        del c["read"], c["seconds"]
    return by


def report(runs: list[Run], path: str):
    s = summarize(runs)
    md = ["# Simulation: reagiert der Agent, und wie?", "",
          "| Leseweg | Bewertung | gelesen (0..1) | Treffer | kritisch | verpasst | teilweise | Sek./Runde | Fehler |",
          "|---|---|---|---|---|---|---|---|---|"]
    for cfg, c in s.items():
        reader, judge = cfg.split(" | judge ")
        md.append(f"| {reader} | {judge} | {c['read_mean']} | {c['hit']} | {c['critical']} | {c['miss']} | "
                  f"{c['partial']} | {c['seconds_mean']} | {c['errors']} |")
    md += ["", "Treffer = erwartete Reaktion (Fehler rot, Hilfe bei Frage, Wellenlinie bei Gekritzel). "
           "Kritisch = falsches Grün auf einem Fehler oder falsches Rot auf richtiger Zeile.", ""]
    for r in runs:
        md.append(f"## {r.scenario} — {r.config}")
        for l in r.lines:
            md.append(f"- `{l['text']}` (erwartet: {l['expect']}) gelesen als `{l['read_as']}` "
                      f"({l['read_score']}) → {', '.join(l['verdicts']) or 'keine Reaktion'} → **{l['outcome']}**")
        for rd in r.rounds:
            md.append(f"  - nach Zeile {rd['after_line'] + 1} ({rd['seconds']} s): {'; '.join(rd['marks']) or '—'}")
        for e in r.errors:
            md.append(f"  - Fehler: {e}")
        md.append("")
    Path(path).write_text("\n".join(md))
    Path(path).with_suffix(".json").write_text(json.dumps([asdict(r) for r in runs], ensure_ascii=False, indent=1))
    return s


def main(configs: list[str], scenarios: list[str] | None, out_dir: str, log=print):
    runs = []
    chosen = [s for s in SCENARIOS if not scenarios or s.name in scenarios]
    for cfg in configs:
        reader_spec, _, judge_spec = cfg.partition("@")
        judge_spec = judge_spec or models.DEFAULT
        log(f"== {reader_spec} | judge {judge_spec}")
        for sc in chosen:
            log(f"  {sc.name}")
            runs.append(run_scenario(sc, reader_spec, judge_spec, out_dir, log=log))
            report(runs, os.path.join(out_dir, "REPORT.md"))
    return report(runs, os.path.join(out_dir, "REPORT.md"))
