"""inkpartner demo | inkpartner review PAGE.rm [--subject S] [-o OUT.rm] [--preview OUT.png]"""
from __future__ import annotations

import argparse
import json
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
    r.add_argument("-o", "--out", help="write page + agent layer to this .rm (the input stays untouched)")
    r.add_argument("--preview", help="PNG of the page with the agent's marks")
    a = ap.parse_args(argv)

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
    import anthropic                     # judging always needs the model; reading only without --elements
    kw["client"] = anthropic.Anthropic()
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
