"""inkpartner demo | inkpartner review PAGE.rm [--subject S] [-o OUT.rm] [--preview OUT.png]"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import page as pagemod


def _report(r) -> dict:
    return {"subject": r.subject,
            "checked_by_sympy": r.checked,
            "accepted": [vars(a) for a in r.accepted],
            "rejected": [{**vars(a), "reason": why} for a, why in r.rejected],
            "speech": r.speech,
            "new_strokes": len(r.strokes)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="inkpartner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="render every mark on a simulated page, no tablet, no model")
    d.add_argument("--preview", default="demo.png")
    r = sub.add_parser("review", help="one review round on a .rm page")
    r.add_argument("page")
    r.add_argument("--subject", choices=["math", "code", "diagram", "pm", "prose"])
    r.add_argument("--elements", help="JSON list of elements instead of the model's reading")
    r.add_argument("--proposals", help="JSON list of actions (+ 'speech') instead of the model's judgement; "
                                       "with --elements no model is called (replay)")
    r.add_argument("--model", help=f"model chain, default {{INKPARTNER_MODEL}} or ollama:qwen3.6:35b-a3b")
    r.add_argument("-o", "--out", help="write page + agent layer to this .rm (the input stays untouched)")
    r.add_argument("--preview", help="PNG of the page with the agent's marks")
    w = sub.add_parser("watch", help="watch the tablet, review where the student writes, write back")
    w.add_argument("--host", default="remarkable")
    w.add_argument("--model", help="model chain, default ollama:qwen3.6:35b-a3b")
    w.add_argument("--subject", choices=["math", "code", "diagram", "pm", "prose"])
    w.add_argument("--interval", type=float, default=3.0)
    w.add_argument("--settle", type=float, default=4.0, help="seconds without a new stroke before a review")
    w.add_argument("--allow-restart", action="store_true",
                   help="LAST RESORT: allow the file path; it restarts the notes app and logs the student out")
    w.add_argument("--restart-quiet", type=float, default=1800.0,
                   help="seconds without a change on any page before a restart may happen")
    w.add_argument("--no-pen", action="store_true", help="do not use the V-Pen path")
    w.add_argument("--once", action="store_true", help="stop after the first review")
    ps = sub.add_parser("pensim", help="round 4: pen path through a simulated zoomed/scrolled screen, no model")
    ps.add_argument("--out", default="sim-out-pen")
    ps.add_argument("--case", action="append", help="only these cases (default: all)")
    pt = sub.add_parser("pentest", help="ONE guarded pen delivery on the tablet: a small check next to the "
                                       "last line of the open page, probe first, read back")
    pt.add_argument("--host", default="remarkable")
    pt.add_argument("--wait", type=float, default=2.0, help="seconds between read-backs")
    sm = sub.add_parser("sim", help="simulated student + simulated tablet + real agent; compare readers/models")
    sm.add_argument("configs", nargs="+", help="READER@JUDGE, e.g. vlm:ollama:qwen3.6:35b-a3b@ollama:qwen3.6:35b-a3b, "
                                              "lines:ollama:gemma4:26b@..., ocr:apple@ollama-text:gpt-oss:20b")
    sm.add_argument("--scenario", action="append", help="only these scenarios (default: all)")
    sm.add_argument("--out", default="sim-out")
    sm.add_argument("--real", help="JSON with real pages and their truth (replayed line by line)")
    sm.add_argument("--rescore", help="score a saved REPORT.json again instead of running")
    a = ap.parse_args(argv)

    if a.cmd == "pensim":
        from . import simpen
        print(json.dumps(simpen.main(a.out, a.case), ensure_ascii=False, indent=1))
        return 0

    if a.cmd == "pentest":
        from . import watch
        print(json.dumps(watch.pentest(a.host, wait_s=a.wait), ensure_ascii=False, indent=1))
        return 0

    if a.cmd == "sim":
        from . import sim
        if a.rescore:
            runs = sim.rescore(a.rescore, a.real)
            print(json.dumps(sim.report(runs, os.path.join(a.out, "REPORT.md")), indent=1))
            return 0
        summary = sim.main(a.configs, a.scenario, a.out, log=lambda *x: print(*x, flush=True), real=a.real)
        print(json.dumps(summary, indent=1))
        return 0

    if a.cmd == "watch":
        from . import watch
        watch.run(a.host, a.model, a.subject, a.interval, a.once, settle_s=a.settle,
                  allow_restart=a.allow_restart, restart_quiet_s=a.restart_quiet, pen=not a.no_pen)
        return 0

    if a.cmd == "demo":
        from . import demo
        strokes, ink, rounds = demo.build()
        pagemod.render(strokes + ink, height=1700).save(a.preview)
        json.dump([_report(x) for x in rounds], sys.stdout, ensure_ascii=False, indent=1)
        print(f"\npreview: {a.preview}", file=sys.stderr)
        return 0

    from . import review
    from .elements import from_dicts
    strokes = pagemod.read_strokes(a.page)
    kw = {"subject": a.subject}
    if a.elements:
        kw["elements"] = from_dicts(json.load(open(a.elements)))
    if a.proposals:
        from .plan import Action
        kw["proposals"] = [(Action(**{k: v for k, v in d.items() if k != "speech"}), d.get("speech", ""))
                           for d in json.load(open(a.proposals))]
    if not (a.elements and a.proposals):
        from . import models
        kw["model"] = models.get(a.model)
    result = review.run(strokes, **kw)
    if a.out:
        print(json.dumps(pagemod.append_strokes(a.page, result.strokes, a.out)), file=sys.stderr)
    if a.preview:
        pagemod.render(strokes + result.strokes).save(a.preview)
    json.dump(_report(result), sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
