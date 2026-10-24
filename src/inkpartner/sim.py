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
    box: list | None = None        # real pages: where this line is on the page
    draw: str = ""                 # a drawing instead of writing: "nn:2,3,1" or "graph:AB,AC,BD"


@dataclass
class Scenario:
    name: str
    subject: str
    lines: list[Line]
    source: str | None = None      # a real .rm page: its strokes are replayed line by line


def real_line_ink(sc: Scenario) -> list[list[dict]]:
    """Split a real page into the scenario's lines: every student stroke goes to the line whose box
    holds its centre (else the nearest). Strokes taller than 600 px are dropped - on 2026-10-23 that
    was the agent's own garbage from a failed pen test, not the student's writing."""
    strokes = [s for s in pagemod.read_strokes(sc.source) if s["author"] == "user"]
    out = [[] for _ in sc.lines]
    for s in strokes:
        b = marks.bbox_of([s])
        if b[3] - b[1] > 600:
            continue
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2

        def dist(l):
            x0, y0, x1, y1 = l.box
            return max(x0 - cx, 0, cx - x1) + max(y0 - cy, 0, cy - y1)
        out[min(range(len(sc.lines)), key=lambda i: dist(sc.lines[i]))].append(s)
    return out


SCENARIOS = [
    Scenario("distributiv-fehler", "math", [Line("3(x+2)=15", "ok"), Line("3x+2=15", "wrong")]),
    Scenario("lineare-gleichung-richtig", "math", [Line("2x+4=10", "ok"), Line("2x=6", "ok"), Line("x=3", "ok")]),
    Scenario("hilfe-binom-hoch-3", "math", [Line("(3x+4y)^3 = ?", "help")]),
    Scenario("binom-hoch-4-falsch", "math", [Line("(z+x)^4 =", "ok"), Line("z^4+zx^4+z^4x+x^4", "wrong")]),
    Scenario("quadratische-ergaenzung", "math", [Line("x^2+6x=7", "ok"), Line("(x+3)^2=16", "ok"),
                                                 Line("x+3=5", "wrong")]),
    Scenario("gekritzel", "math", [Line("2x=8", "ok"), Line("~", "unreadable")]),
    Scenario("bruch-fehler", "math", [Line("1/2+1/3", "ok"), Line("2/5", "wrong")]),
    Scenario("vorzeichen-fehler", "math", [Line("5-2(x-3)=1", "ok"), Line("5-2x-6=1", "wrong")]),
    Scenario("hilfe-in-worten", "math", [Line("x^2-5x+6=0", "ok"), Line("wie geht das?", "help")]),
    Scenario("potenzregel-richtig", "math", [Line("(a*b)^3", "ok"), Line("a^3*b^3", "ok")]),
    Scenario("mehrschritt-richtig", "math", [Line("3(x-1)=2x+5", "ok"), Line("3x-3=2x+5", "ok"),
                                             Line("x=8", "ok")]),
]


# Round 6: other subjects. Umlauts written as ue/ae (the single-stroke font folds them anyway).
SUBJECT_SCENARIOS = [
    Scenario("code-fakultaet-basisfall", "code", [Line("def fak(n):", "ok"), Line("if n == 0: return 0", "wrong"),
                                                  Line("return n * fak(n-1)", "ok")]),
    Scenario("code-summe-richtig", "code", [Line("s = 0", "ok"), Line("for i in range(1, n+1):", "ok"),
                                            Line("s = s + i", "ok")]),
    Scenario("code-binaere-suche", "code", [Line("lo, hi = 0, len(a)-1", "ok"), Line("mid = (lo + hi) / 2", "wrong")]),
    Scenario("code-laufzeit-hilfe", "code", [Line("for i in range(n):", "ok"), Line("for j in range(n): x += 1", "ok"),
                                             Line("Laufzeit?", "help")]),
    Scenario("bwl-deckungsbeitrag", "prose", [Line("DB = Umsatz - Fixkosten", "wrong")]),
    Scenario("bwl-break-even", "prose", [Line("BEP = Fixkosten / DB pro Stueck", "ok")]),
    Scenario("pm-kritischer-pfad", "pm", [Line("Kritischer Pfad = kuerzester Weg", "wrong")]),
    Scenario("pm-meilenstein", "pm", [Line("Meilenstein: Dauer 0", "ok")]),
    Scenario("nn-parameter-falsch", "diagram", [Line("[Netz 2-3-1]", "ok", draw="nn:2,3,1"),
                                                Line("Parameter mit Bias: 9", "wrong")]),
    Scenario("nn-gewichte-richtig", "diagram", [Line("[Netz 2-3-1]", "ok", draw="nn:2,3,1"),
                                                Line("Gewichte ohne Bias: 9", "ok")]),
    Scenario("graph-grad-falsch", "diagram", [Line("[Graph]", "ok", draw="graph:AB,AC,CD"),
                                              Line("Grad von A = 3", "wrong")]),
    Scenario("graph-weg-hilfe", "diagram", [Line("[Graph]", "ok", draw="graph:AB,AC,CD,BD"),
                                            Line("kuerzester Weg von A nach D?", "help")]),
]


def _circle(cx, cy, r, rng, n=28):
    a0 = rng.uniform(0, 6.28)
    return [[cx + r * math.cos(a0 + 2 * math.pi * i / n) + rng.gauss(0, 1.2),
             cy + r * math.sin(a0 + 2 * math.pi * i / n) + rng.gauss(0, 1.2), .6] for i in range(n + 2)]


def _edge(a, b, r, rng):
    (ax, ay), (bx, by) = a, b
    d = max(1.0, math.hypot(bx - ax, by - ay))
    ux, uy = (bx - ax) / d, (by - ay) / d
    return [[ax + ux * r + rng.gauss(0, 1), ay + uy * r + rng.gauss(0, 1), .6],
            [bx - ux * r + rng.gauss(0, 1), by - uy * r + rng.gauss(0, 1), .6]]


def draw(spec: str, origin, rng: random.Random) -> list[dict]:
    """Hand-drawn diagrams: a neural network (layers of circles, all edges between layers) or a small
    graph (lettered circles, edges by letter pairs)."""
    kind, _, arg = spec.partition(":")
    x0, y0 = origin
    strokes, r = [], 26
    if kind == "nn":
        layers = [int(n) for n in arg.split(",")]
        tall = max(layers)
        pos = [[(x0 + 40 + 190 * li, y0 + 40 + 90 * (i + (tall - n) / 2)) for i in range(n)]
               for li, n in enumerate(layers)]
        for col in pos:
            for c in col:
                strokes.append(_circle(*c, r, rng))
        for a, b in zip(pos, pos[1:]):
            for p in a:
                for q in b:
                    strokes.append(_edge(p, q, r, rng))
    elif kind == "graph":
        names = sorted({ch for e in arg.split(",") for ch in e})
        spots = [(0, 0), (220, -60), (220, 120), (440, 40), (440, 220)]
        pos = {n: (x0 + 40 + spots[i][0], y0 + 100 + spots[i][1]) for i, n in enumerate(names)}
        for n, c in pos.items():
            strokes.append(_circle(*c, r + 6, rng))
            for s in marks.text(n, (c[0] - 12, c[1] - 16), height=32):
                strokes.append([[p[0], p[1], .6] for p in s["points"]])
        for e in arg.split(","):
            strokes.append(_edge(pos[e[0]], pos[e[1]], r + 6, rng))
    return [{"points": pts, "color": "black", "width": 3, "author": "user"} for pts in strokes]


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

    def screenshot(self):
        """Like the device thumbnail: 384x512, grid paper, every layer (agent notes included), the
        view unzoomed at the top of the page (viewport measured on the device 2026-10-23: scale 1)."""
        from PIL import Image, ImageDraw
        from .viewport import Viewport
        img = Image.new("RGB", (384, 512), (250, 250, 248))
        d = ImageDraw.Draw(img)
        for x in range(0, 384, 12):
            d.line([(x, 0), (x, 512)], fill=(214, 214, 214))
        for y in range(0, 512, 12):
            d.line([(0, y), (384, y)], fill=(214, 214, 214))
        k = 384 / 1620
        for s in self.strokes():
            col = pagemod.RGB.get(s.get("color"), (20, 20, 20))
            pts = [(p[0] * k, p[1] * k) for p in s["points"]]
            if len(pts) > 1:
                d.line(pts, fill=col, width=1 if s["author"] == "agent" else 2)
        return pagemod.png_bytes(img), Viewport(1.0, 0.0, 0.0, 1.0)


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
    outcome: str           # hit | miss | ok | critical | partial | noise
    box_iou: float | None = None   # how well the element box (where marks land) covers the true line


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def assign(texts: list[str], truth: list[str]) -> dict[int, int]:
    """element index -> truth line index, by reading (a mark belongs to the line it was read as);
    an element that matches no truth line well enough (< 0.5) belongs to none."""
    out = {}
    for i, t in enumerate(texts):
        scores = [_sim(t, tr) for tr in truth]
        if scores and max(scores) >= 0.5:
            out[i] = scores.index(max(scores))
    return out


def score_lines(lines: list[Line], boxes: list, rounds: list[dict]) -> list[LineResult]:
    """`rounds`: what the agent read and marked each round ({'read': [...], 'boxes': [...], 'marks':
    [(verdict, element index)]}). Marks are mapped to lines through the text they were read as."""
    truth = [l.text for l in lines]
    found = [set() for _ in lines]
    last = rounds[-1] if rounds else {"read": [], "boxes": []}
    for rd in rounds:
        idx = assign(rd["read"], truth)
        for verdict, ei in rd["marks"]:
            if ei in idx:
                found[idx[ei]].add(verdict)
    out = []
    last_idx = assign(last["read"], truth)
    for li, (line, box) in enumerate(zip(lines, boxes)):
        els = [ei for ei, l in last_idx.items() if l == li]
        read_as = last["read"][els[0]] if els else ""
        iou = _iou(box, last["boxes"][els[0]]) if els and last.get("boxes") else None
        v = found[li]
        if line.expect == "wrong":
            outcome = "critical" if "correct" in v else "hit" if "wrong" in v else "partial" if v & {"hint", "help"} else "miss"
        elif line.expect == "ok":
            outcome = "critical" if "wrong" in v else "noise" if v & {"help", "hint"} else "ok"
        elif line.expect == "help":
            outcome = "hit" if "help" in v else "partial" if "hint" in v else "miss"
        else:
            outcome = "critical" if "correct" in v else "hit" if "unreadable" in v else "miss"
        r = LineResult(line.text, line.expect, read_as, round(_sim(line.text, read_as), 2) if read_as else 0.0,
                       sorted(v), outcome)
        r.box_iou = None if iou is None else round(iou, 2)
        out.append(r)
    return out


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
    reader = readers.get(reader_spec, screenshot=tab.screenshot)
    judge = models.get(judge_spec)
    w = Watcher(tab, judge, subject=sc.subject, pen=SimPen(tab), log=lambda *a: None, reader=reader,
                judge_model=judge, state_file=os.path.join(work, "state.json"))
    w.verify_wait_s, w.verify_tries = 0, 1
    run = Run(f"{reader_spec} | judge {judge_spec}", sc.name)
    w.tick()                                           # the empty page is old news
    y = 220.0
    boxes = []
    real = real_line_ink(sc) if sc.source else None
    for i, line in enumerate(sc.lines):
        height = rng.uniform(70, 95)
        tab.clock += 30
        if real is not None:
            ink = [dict(s, points=[list(p) for p in s["points"]]) for s in real[i]]
            if not ink:
                continue
        elif line.draw:
            ink = draw(line.draw, (200 + rng.uniform(-30, 30), y), rng)
        else:
            ink = handwrite(line.text, (200 + rng.uniform(-30, 30), y), height, rng)
        tab.student_writes(ink)
        boxes.append(line.box or marks.bbox_of(ink))
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
            ids = [e.id for e in r.elements]
            run.rounds.append({"after_line": i, "seconds": dt, "subject": r.subject,
                               "read": [e.text for e in r.elements],
                               "boxes": [[round(v) for v in e.bbox] for e in r.elements],
                               "verdicts": [[a.verdict, ids.index(a.element)] for a in r.accepted
                                            if a.element in ids],
                               "marks": [f"{a.verdict}/{a.mark} {a.element} {a.text}".strip() for a in r.accepted],
                               "rejected": [f"{a.verdict}/{a.mark} {a.element}: {why}" for a, why in r.rejected]})
            log(f"    after line {i + 1} ({dt}s): read {[e.text for e in r.elements]} -> "
                f"{[f'{a.verdict}/{a.mark}' for a in r.accepted]}")
        all_ink = tab.strokes()
        y = max(p[1] for s in all_ink for p in s["points"]) + 90
    sc_lines = [l for l, ink in zip(sc.lines, real or sc.lines) if ink]
    rounds = [{"read": rd["read"], "boxes": rd["boxes"], "marks": rd["verdicts"]} for rd in run.rounds]
    run.lines = [asdict(x) for x in score_lines(sc_lines, boxes, rounds)]
    os.makedirs(out_dir, exist_ok=True)
    run.preview = os.path.join(out_dir, f"{_slug(run.config)}__{sc.name}.png")
    pagemod.render(tab.strokes(), scale=0.4).save(run.preview)
    return run


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", s).strip("-")[:80]


def summarize(runs: list[Run]) -> dict:
    by = {}
    for r in runs:
        c = by.setdefault(r.config, {"lines": 0, "hit": 0, "critical": 0, "miss": 0, "partial": 0, "ok": 0, "noise": 0,
                                     "read": [], "seconds": [], "errors": 0})
        for l in r.lines:
            c["lines"] += 1
            c[l["outcome"]] += 1
            c["read"].append(l["read_score"])
            if l.get("box_iou") is not None:
                c.setdefault("iou", []).append(l["box_iou"])
        c["seconds"] += [x["seconds"] for x in r.rounds]
        c["errors"] += len(r.errors)
    for c in by.values():
        c["read_mean"] = round(sum(c["read"]) / max(1, len(c["read"])), 2)
        c["seconds_mean"] = round(sum(c["seconds"]) / max(1, len(c["seconds"])), 1)
        iou = c.pop("iou", [])
        c["box_iou_mean"] = round(sum(iou) / len(iou), 2) if iou else None
        del c["read"], c["seconds"]
    return by


def report(runs: list[Run], path: str):
    s = summarize(runs)
    md = ["# Simulation: reagiert der Agent, und wie?", "",
          "| Leseweg | Bewertung | gelesen (0..1) | Box trifft (IoU) | Treffer | kritisch | verpasst | teilweise | ungefragt | Sek./Runde | Fehler |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for cfg, c in s.items():
        reader, judge = cfg.split(" | judge ")
        md.append(f"| {reader} | {judge} | {c['read_mean']} | {c['box_iou_mean']} | {c['hit']} | {c['critical']} | {c['miss']} | "
                  f"{c['partial']} | {c['noise']} | {c['seconds_mean']} | {c['errors']} |")
    md += ["", "Treffer = erwartete Reaktion (Fehler rot, Hilfe bei Frage, Wellenlinie bei Gekritzel). "
           "Kritisch = falsches Grün auf einem Fehler oder falsches Rot auf richtiger Zeile. "
           "Ungefragt = Hilfe oder Hinweis auf einer richtigen Zeile, obwohl niemand gefragt hat.", ""]
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


def real_scenarios(path: str) -> list[Scenario]:
    """Real pages with their truth, from a JSON file: [{name, subject, source, lines: [{text, expect, box}]}]"""
    out = []
    for d in json.loads(Path(path).read_text()):
        src = d["source"] if os.path.isabs(d["source"]) else os.path.join(os.path.dirname(path), d["source"])
        out.append(Scenario(d["name"], d["subject"], [Line(**l) for l in d["lines"]], src))
    return out


def rescore(json_path: str, real: str | None = None) -> list[Run]:
    """Score saved runs again with the current scoring (older runs lack boxes: no IoU then)."""
    pool = {s.name: s for s in SCENARIOS + (real_scenarios(real) if real else [])}
    runs = []
    for d in json.loads(Path(json_path).read_text()):
        sc = pool.get(d["scenario"])
        if not sc:
            continue
        lines = [l for l in sc.lines if any(x["text"] == l.text for x in d["lines"])] or sc.lines
        boxes = [l.box or [0, 0, 1, 1] for l in lines]
        rounds = []
        for rd in d["rounds"]:
            marks_ = rd.get("verdicts")
            if marks_ is None:          # old format: "verdict/mark e3 text"
                marks_ = []
                for m in rd["marks"]:
                    v, _, rest = m.partition("/")
                    eid = rest.split()[1] if len(rest.split()) > 1 else ""
                    if eid.startswith("e") and eid[1:].isdigit():
                        marks_.append([v, int(eid[1:])])
            rounds.append({"read": rd["read"], "boxes": rd.get("boxes", []), "marks": marks_})
        run = Run(d["config"], d["scenario"], rounds=d["rounds"], errors=d["errors"], preview=d["preview"])
        run.lines = [asdict(x) for x in score_lines(lines, boxes, rounds)]
        if not any(rd.get("boxes") for rd in rounds):
            for l in run.lines:
                l["box_iou"] = None
        runs.append(run)
    return runs


def main(configs: list[str], scenarios: list[str] | None, out_dir: str, log=print, real: str | None = None):
    runs = []
    pool = SCENARIOS + SUBJECT_SCENARIOS + (real_scenarios(real) if real else [])
    if scenarios == ["subjects"]:
        chosen = SUBJECT_SCENARIOS
    elif scenarios:
        chosen = [s for s in pool if s.name in scenarios]
    else:
        chosen = [s for s in pool if s not in SUBJECT_SCENARIOS]
    for cfg in configs:
        reader_spec, _, judge_spec = cfg.partition("@")
        judge_spec = judge_spec or models.DEFAULT
        log(f"== {reader_spec} | judge {judge_spec}")
        for sc in chosen:
            log(f"  {sc.name}")
            runs.append(run_scenario(sc, reader_spec, judge_spec, out_dir, log=log))
            report(runs, os.path.join(out_dir, "REPORT.md"))
    return report(runs, os.path.join(out_dir, "REPORT.md"))
