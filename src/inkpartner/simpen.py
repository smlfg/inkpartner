"""Round 4: does the pen path write where it means to - zoomed, scrolled, with a stale screenshot?

No model involved: a fixed page, fixed marks, a simulated screen. Measures only the way back.

The simulated tablet knows the TRUE viewport (what the screen really shows) and the viewport of its
last screenshot (thumbnail). They differ when the student scrolled or zoomed without writing: no
save, so no new thumbnail. Pen events are mapped through the true viewport, the way the screen
does it, and land in the student's layer in the pen's colour, as on the device. Every save (also
the agent's own ink) brings a fresh thumbnail.

    outcome     delivered: every mark confirmed where planned | refused: nothing written, waits
                (that is right when the mark is off-screen) | wrong: anything else
    stray       pen strokes that did not land where planned (a probe that missed, at most)
    on ink      stray strokes touching the student's writing - must be 0
"""
from __future__ import annotations

import json
import math
import os
import random
import tempfile
from dataclasses import asdict, dataclass, field

from . import marks, page as pagemod, verify
from .guards import GuardError
from .penpath import PenPath, landing, new_strokes
from .sim import SimTablet, handwrite
from .viewport import SCREEN, Viewport


class ScreenTablet(SimTablet):
    def __init__(self, workdir, view: Viewport, thumb: Viewport):
        super().__init__(workdir)
        self.view, self.thumb = view, thumb

    def thumbnail(self, rel):
        from PIL import Image, ImageDraw
        W, H = 384, 512
        k = W / SCREEN[0]
        img = Image.new("RGB", (W, H), (250, 250, 248))
        d = ImageDraw.Draw(img)
        v = self.thumb
        for g in range(0, 2200, 52):                   # grid paper, drawn in page space
            for a, b in (((g, 0), (g, 2160)), ((0, g), (1620, g))):
                pa, pb = v.to_screen(*a), v.to_screen(*b)
                d.line([(pa[0] * k, pa[1] * k), (pb[0] * k, pb[1] * k)], fill=(214, 214, 214))
        for s in self.strokes():
            pts = [(x * k, y * k) for x, y in (v.to_screen(p[0], p[1]) for p in s["points"])]
            if len(pts) > 1:
                d.line(pts, fill=pagemod.RGB.get(s.get("color"), (20, 20, 20)), width=max(1, round(2 * v.scale)))
        return pagemod.png_bytes(img)

    def strokes_of(self, data):
        return self.strokes()

    def send(self, screen_strokes):
        ink = []
        for s in screen_strokes:
            pts = [[*self.view.to_page(x, y), 0.5] for x, y in (p[:2] for p in s["points"])
                   if 0 <= x <= SCREEN[0] and 0 <= y <= SCREEN[1]]
            if len(pts) > 1:
                ink.append({"points": pts, "color": "black"})
        if ink:
            self._append(ink, "Layer 1")               # the pen writes into the student's layer
        self.thumb = self.view                         # a save: the next thumbnail shows the real view


class Device:
    """What PenPath needs, on top of the simulated tablet."""

    def __init__(self, tab):
        self.tab = tab

    def thumbnail(self, rel):
        return self.tab.thumbnail(rel)

    def fetch(self, rel):
        return self.tab.fetch(rel)

    def strokes(self, data):
        return self.tab.strokes()

    def send(self, screen):
        self.tab.send(screen)


@dataclass
class Case:
    name: str
    view: tuple            # true viewport (scale, ox, oy)
    thumb: tuple           # viewport of the last screenshot
    expect: str            # delivered | refused
    lines: int = 3


CASES = [
    Case("normal", (1, 0, 0), (1, 0, 0), "delivered"),
    Case("gescrollt", (1, 0, -180), (1, 0, -180), "delivered"),
    Case("zoom-1.5", (1.5, -200, -120), (1.5, -200, -120), "delivered"),
    Case("zoom-0.8", (0.8, 160, 60), (0.8, 160, 60), "delivered"),
    Case("zoom-2-ausserhalb", (2.0, -1300, -200), (2.0, -1300, -200), "refused"),
    Case("veraltet-gescrollt", (1, 0, -150), (1, 0, 0), "delivered"),
    Case("veraltet-zoom", (1.3, -100, -60), (1, 0, 0), "delivered"),
    Case("veraltet-leicht", (1, 0, -8), (1, 0, 0), "delivered"),
    Case("veraltet-ausserhalb", (2.0, -1300, -200), (1, 0, 0), "refused"),
    Case("veraltet-nach-links", (1.2, 150, -40), (1, 0, 0), "delivered"),
    Case("veraltet-eine-zeile", (1, 0, 170), (1, 0, 0), "delivered"),
    Case("veraltet-zwei-zeilen", (1, 0, 340), (1, 0, 0), "delivered"),
    Case("kurze-seite", (1, 0, 0), (1, 0, 0), "delivered", lines=1),
]

TEXTS = ["3(x+2)=15", "3x+2=15", "3x=13"]


@dataclass
class CaseResult:
    case: str
    expect: str
    outcome: str
    attempts: int
    refusals: list = field(default_factory=list)
    error_px: float | None = None        # mean distance of the delivered marks from their plan
    stray: int = 0
    stray_on_ink: int = 0
    probe_errors: list = field(default_factory=list)
    viewports: list = field(default_factory=list)
    preview: str = ""


def _bbox(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _touches(a, b, pad=4):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


def build_page(tab, n, rng):
    y, boxes = 220.0, []
    for t in TEXTS[:n]:
        ink = handwrite(t, (200 + rng.uniform(-20, 20), y), rng.uniform(75, 90), rng)
        tab.student_writes(ink)
        boxes.append(marks.bbox_of(ink))
        y = boxes[-1][3] + 90
    plan = []
    for k, s in enumerate(marks.check(boxes[0])):
        plan.append({**s, "action": "check"})
    if n > 1:
        for s in marks.circle(boxes[1]):
            plan.append({**s, "action": "circle"})
        b = boxes[1]
        for s in marks.text("3 mal 2", (b[2] + 60, b[1]), height=50):
            plan.append({**s, "action": "note"})
    return plan


def run_case(c: Case, out_dir: str, seed=4, max_attempts=2) -> CaseResult:
    rng = random.Random(seed)
    tab = ScreenTablet(tempfile.mkdtemp(prefix="inkp-pen-"), Viewport(*c.view, 1.0), Viewport(*c.thumb, 1.0))
    plan = build_page(tab, c.lines, rng)
    student = [s for s in tab.strokes()]
    path = PenPath(Device(tab), wait_s=0, tries=1, sleep=lambda s: None)
    res = CaseResult(c.name, c.expect, "refused", 0)
    before = tab.strokes()
    landed = []
    for _ in range(max_attempts):
        res.attempts += 1
        try:
            path.deliver(plan, SimTablet.REL)
            landed += path.landed
            res.viewports.append(path.last.get("viewport"))
            res.probe_errors.append(path.last.get("probe_error_px"))
            res.outcome = "delivered"
            break
        except GuardError as e:
            landed += path.landed
            res.viewports.append(path.last.get("viewport"))
            res.probe_errors.append(path.last.get("probe_error_px"))
            res.refusals.append(str(e).split(":")[0])
            if not str(e).startswith("R-PROBE"):
                break                                  # nothing to learn: the mark waits
    after = tab.strokes()
    states = verify.verify(plan, before, after)
    if res.outcome == "delivered" and not all(v == "confirmed" for v in states.values()):
        res.outcome = "wrong"
    # which landed strokes match a planned stroke (within 12 px), which are strays
    errors = []
    for s in new_strokes(before, after):
        best = min((math.hypot(*landing(p, [s])[:2]) for p in plan), default=1e9)
        if best <= 12:
            errors.append(best)
        else:
            res.stray += 1
            if any(_touches(_bbox(s["points"]), _bbox(u["points"])) for u in student):
                res.stray_on_ink += 1
    res.error_px = round(sum(errors) / len(errors), 1) if errors else None
    os.makedirs(out_dir, exist_ok=True)
    res.preview = os.path.join(out_dir, f"{c.name}.png")
    pagemod.render(after, scale=0.4).save(res.preview)
    return res


def summarize(results):
    deliverable = [r for r in results if r.expect == "delivered"]
    return {
        "faelle": len(results),
        "richtig": sum(r.outcome == r.expect for r in results),
        "zugestellt_von_zustellbar": f"{sum(r.outcome == 'delivered' for r in deliverable)}/{len(deliverable)}",
        "falsch": sum(r.outcome == "wrong" for r in results),
        "streustriche": sum(r.stray for r in results),
        "streustriche_auf_schrift": sum(r.stray_on_ink for r in results),
        "fehler_px_mittel": round(sum(r.error_px for r in results if r.error_px is not None)
                                  / max(1, sum(r.error_px is not None for r in results)), 1),
    }


def report(results, path):
    s = summarize(results)
    rows = ["# Runde 4: Zurückschreiben mit dem Stift (simuliert)", "",
            "| Fall | erwartet | Ergebnis | Versuche | abgelehnt wegen | Probe-Fehler px | Abweichung px | Streustriche | davon auf Schrift |",
            "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        rows.append(f"| {r.case} | {r.expect} | **{r.outcome}** | {r.attempts} | {', '.join(r.refusals) or '–'} | "
                    f"{', '.join(str(p) for p in r.probe_errors if p is not None) or '–'} | "
                    f"{r.error_px if r.error_px is not None else '–'} | {r.stray} | {r.stray_on_ink} |")
    rows += ["", "```", json.dumps(s, ensure_ascii=False, indent=1), "```"]
    with open(path, "w") as f:
        f.write("\n".join(rows) + "\n")
    with open(path.replace(".md", ".json"), "w") as f:
        json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=1)
    return s


def main(out_dir="sim-out-pen", names=None, log=print):
    results = []
    for c in CASES:
        if names and c.name not in names:
            continue
        r = run_case(c, out_dir)
        log(f"{c.name:22} expect {c.expect:9} -> {r.outcome:9} attempts {r.attempts} "
            f"refusals {r.refusals} probe {r.probe_errors} err {r.error_px} stray {r.stray}/{r.stray_on_ink} "
            f"vp {r.viewports}")
        results.append(r)
    return report(results, os.path.join(out_dir, "REPORT.md"))


if __name__ == "__main__":
    import sys
    print(json.dumps(main(sys.argv[1] if len(sys.argv) > 1 else "sim-out-pen"), indent=1))
