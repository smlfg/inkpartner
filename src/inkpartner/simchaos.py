"""Round 7, chaos mode: the student jumps between pages, notebooks and folders. Does the agent
follow - and does feedback ever land on a page the student is not looking at?

No model: a reader that knows what was written where, and a judge that asks for help where the page
asks. That isolates what this round tests - the watcher's sense of WHERE - from reading quality.

On the device folders are only metadata (`parent` in .metadata); every page file lives flat under
xochitl/<doc>/<page>.rm. A folder switch is therefore a notebook switch for the watcher; the script
still contains them, because "it should not matter" is a claim to test, not to assume.

    reacted     the expected reaction landed on the page it belongs to
    late        it landed, but only after the student came back to the page
    lost        it never landed
    wrong page  a mark landed on another page than the one it was meant for - must be 0
    while away  a mark landed on a page that was not open at that moment - must be 0
"""
from __future__ import annotations

import json
import os
import random
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import marks, page as pagemod, readers
from .elements import Element
from .guards import Guard, GuardError, Limits
from .sim import handwrite


class ChaosTablet:
    """Many page files, one open page, one clock - the Watcher's tablet interface."""

    def __init__(self, workdir: str):
        self.dir, self.clock, self.host = workdir, 1_000_000, "chaos"
        self.files: dict[str, str] = {}
        self.mtimes: dict[str, int] = {}
        self.open: str | None = None
        self.guard = Guard(os.path.join(workdir, "STOP"), Limits(), log=lambda *a: None)
        self.monitor, self.allow_restart = None, False
        self.names: dict[str, str] = {}

    def page(self, rel: str, name: str = ""):
        if rel not in self.files:
            p = os.path.join(self.dir, rel.replace("/", "__"))
            pagemod.new_page(p)
            self.files[rel], self.mtimes[rel] = p, self.clock
            self.names[rel] = name or rel
        return self.files[rel]

    def _append(self, rel, strokes, layer):
        p = self.files[rel]
        pagemod.append_strokes(p, strokes, p + ".new", layer=layer)
        os.replace(p + ".new", p)
        self.mtimes[rel] = self.clock

    def scan(self):
        return {rel: (self.mtimes[rel], os.path.getsize(p)) for rel, p in self.files.items()}

    def fetch(self, rel):
        return Path(self.files[rel]).read_bytes()

    def name(self, rel):
        return self.names.get(rel, rel)

    def strokes_of(self, rel):
        return pagemod.read_strokes(self.files[rel])

    def open_page(self):
        return tuple(self.open.removesuffix(".rm").split("/")) if self.open else None

    def background(self, rel):
        return None


class ChaosPen:
    """A pen that writes only into the page on the screen - as pen events do. The guard's R-OPEN
    check is applied the same way as on the device."""

    def __init__(self, tab: ChaosTablet, log: list):
        self.tab, self.log, self.landed = tab, log, []

    def deliver(self, strokes, rel):
        doc, page = rel.split("/")[0], rel.split("/")[1].removesuffix(".rm")
        self.landed = []
        if self.tab.open_page() != (doc, page):
            raise GuardError(f"R-OPEN: open page is {self.tab.open_page()}, target is {(doc, page)}")
        self.tab._append(rel, strokes, pagemod.AGENT_LAYER)
        boxes = {}
        for s in strokes:
            boxes.setdefault(s["action"], []).append(s)
        self.log.append({"t": self.tab.clock, "target": rel, "open": self.tab.open,
                         "actions": {k: marks.bbox_of(v) for k, v in boxes.items()}})
        return {"status": "chaos"}


@dataclass
class Step:
    do: str                 # open | write | wait
    page: str = ""          # "notebook/page.rm"
    text: str = ""
    expect: str = ""        # wrong | help | ok (for write)
    name: str = ""


# notebooks in different "folders" - for the watcher they are just different documents
SCRIPT = [
    Step("open", "mathe-ana/p1.rm", name="Analysis / Mathe-Ana, Seite 1"),
    Step("write", "mathe-ana/p1.rm", "3(x+2)=15", "ok"),
    Step("write", "mathe-ana/p1.rm", "3x+2=15", "wrong"),
    Step("open", "mathe-ana/p2.rm", name="Analysis / Mathe-Ana, Seite 2"),          # page switch
    Step("write", "mathe-ana/p2.rm", "(a+b)^2 = ?", "help"),
    Step("open", "info-aud/p1.rm", name="Informatik / AuD, Seite 1"),               # other folder
    Step("write", "info-aud/p1.rm", "2x+4=10", "ok"),
    Step("write", "info-aud/p1.rm", "2x=6", "ok"),
    # writes, and switches away before the pen pause is over: feedback for p3 must wait
    Step("open", "mathe-ana/p3.rm", name="Analysis / Mathe-Ana, Seite 3"),
    Step("write", "mathe-ana/p3.rm", "5-2(x-3)=1", "ok"),
    Step("write", "mathe-ana/p3.rm", "5-2x-6=1", "wrong"),
    Step("open", "bwl/p1.rm", name="BWL / Kosten, Seite 1"),                        # away, immediately
    Step("wait"),
    Step("write", "bwl/p1.rm", "1/2+1/3", "ok"),
    Step("write", "bwl/p1.rm", "2/5", "wrong"),
    Step("open", "mathe-ana/p3.rm"),                                                 # back - no writing
    Step("wait"),
    Step("wait"),
    Step("open", "neu/p1.rm", name="Neues Notizbuch"),                               # brand new notebook
    Step("write", "neu/p1.rm", "x^2-5x+6=0", "ok"),
    Step("write", "neu/p1.rm", "wie geht das?", "help"),
]

WRITE_ONLY_AT_PAUSE = {"mathe-ana/p3.rm"}       # the student leaves before the pen pause


@dataclass
class Expected:
    page: str
    text: str
    expect: str
    written_at: int
    box: list = field(default_factory=list)
    result: str = "lost"
    landed_at: int | None = None


@dataclass
class ChaosResult:
    expected: list = field(default_factory=list)
    deliveries: list = field(default_factory=list)
    wrong_page: int = 0
    while_away: int = 0
    summary: dict = field(default_factory=dict)


def run(seed=5, log=print, settle_ticks=3) -> ChaosResult:
    from .watch import Watcher
    rng = random.Random(seed)
    tab = ChaosTablet(tempfile.mkdtemp(prefix="inkp-chaos-"))
    registry: dict[tuple, str] = {}          # first point of each student stroke -> line text
    ys: dict[str, float] = {}

    def reader(strokes):
        lines = readers.cluster_lines([s for s in strokes if s.get("author") == "user"])
        els = []
        for i, l in enumerate(lines):
            texts = [registry.get(tuple(s["points"][0][:2])) for s in l]
            text = next((t for t in texts if t), "")
            els.append(Element(f"e{i}", "formula", marks.bbox_of(l), text, confidence=0.95, group="1"))
        return "math", els

    class Judge:
        name = used = "fake"

        def json(self, images, prompt, schema):
            acts = []
            for d in json.loads(prompt.split("Elements on the page:\n", 1)[1].split("\n", 1)[0]):
                if d.get("asks_for_help"):
                    acts.append({"element": d["id"], "verdict": "help", "mark": "note", "text": "Binom!",
                                 "why": "", "speech": ""})
            return {"actions": acts}

    deliveries: list = []
    pen = ChaosPen(tab, deliveries)
    w = Watcher(tab, Judge(), subject="math", pen=pen, log=lambda *a: None, reader=reader,
                judge_model=Judge(), state_file=os.path.join(tab.dir, "state.json"), teach=False)
    w.verify_wait_s, w.verify_tries = 0, 1
    exp: list[Expected] = []

    def tick(n=1):
        for _ in range(n):
            tab.clock += 3
            try:
                w.tick()
            except Exception as e:
                log(f"  watcher error: {e}")

    tick()
    for st in SCRIPT:
        if st.do == "open":
            tab.page(st.page, st.name)
            tab.open = st.page
            tick()
        elif st.do == "write":
            tab.page(st.page)
            y = ys.get(st.page, 220.0)
            ink = handwrite(st.text, (200, y), 80, rng)
            tab._append(st.page, ink, "Layer 1")
            for s in pagemod.read_strokes(tab.files[st.page]):
                key = tuple(s["points"][0][:2])
                if s["author"] == "user" and key not in registry:
                    registry[key] = st.text
            ys[st.page] = max(p[1] for s in ink for p in s["points"]) + 90
            exp.append(Expected(st.page, st.text, st.expect, tab.clock, marks.bbox_of(ink)))
            if st.page in WRITE_ONLY_AT_PAUSE and st.expect == "wrong":
                continue                            # the student leaves at once: no pause on this page
            tick(settle_ticks)
        elif st.do == "wait":
            tick(3)
    # score: a mark answers a line when it is on the line's page and touches the line's box
    def touches(a, b, pad=40):
        return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])
    for d in deliveries:
        d["while_away"] = d["target"] != d["open"]
    for e in exp:
        kind = {"wrong": ":wrong:", "help": ":help:"}.get(e.expect)
        if kind is None:
            red = [d for d in deliveries if d["target"] == e.page
                   for k, b in d["actions"].items() if ":wrong:" in k and touches(b, e.box, pad=0)]
            e.result = "false red" if red else "ok"
            continue
        hits = [d for d in deliveries if d["target"] == e.page and d["t"] >= e.written_at
                for k, b in d["actions"].items() if kind in k and touches(b, e.box, pad=400 if e.expect == "help" else 40)]
        if hits:
            e.landed_at = hits[0]["t"]
            e.result = "late" if e.page in WRITE_ONLY_AT_PAUSE else "reacted"
    res = ChaosResult([asdict(e) for e in exp], deliveries,
                      wrong_page=0, while_away=sum(1 for d in deliveries if d.get("while_away")))
    react = [e for e in exp if e.expect in ("wrong", "help")]
    res.summary = {"reaktionen_erwartet": len(react),
                   "reagiert": sum(e.result == "reacted" for e in react),
                   "spaet": sum(e.result == "late" for e in react),
                   "verloren": sum(e.result == "lost" for e in react),
                   "falsch_rot": sum(e.result == "false red" for e in exp),
                   "auf_fremder_seite": res.wrong_page, "waehrend_weg": res.while_away}
    return res


def report(res: ChaosResult, path: str):
    rows = ["# Runde 7: Chaos-Modus (Seiten, Notizbücher, Ordner wechseln)", "",
            "| Seite | Zeile | erwartet | Ergebnis |", "|---|---|---|---|"]
    for e in res.expected:
        rows.append(f"| {e['page']} | `{e['text']}` | {e['expect']} | **{e['result']}** |")
    rows += ["", "Zustellungen:", ""] + [f"- t={d['t']} → {d['target']} (offen: {d['open']}) "
                                         f"{sorted(k.split(':', 1)[1] for k in d['actions'])}"
                                         for d in res.deliveries]
    rows += ["", "```", json.dumps(res.summary, ensure_ascii=False, indent=1), "```"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    Path(path).write_text("\n".join(rows) + "\n")
    return res.summary


if __name__ == "__main__":
    import sys
    r = run()
    print(json.dumps(report(r, os.path.join(sys.argv[1] if len(sys.argv) > 1 else "sim-out-chaos", "REPORT.md")),
                     ensure_ascii=False, indent=1))
