"""Round 5: which help prompt teaches - measured, not felt.

Every case is a request for help as it would stand on the page. Each prompt variant answers it at
each help level; deterministic checks (tutor.score) and a grader model from another family rate the
answer. The grader never grades its own family's answers by default (gemma grades qwen and MiniMax).

    python -m inkpartner tutoreval --gen ollama:qwen3.6:35b-a3b --gen minimax:MiniMax-M3 \
        --grader ollama:gemma4:26b --out sim-out-tutor
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field

from . import models, tutor


@dataclass
class HelpCase:
    name: str
    task: str
    student: str = ""
    subject: str = "Mathematik"
    spoilers: tuple = ()


CASES = [
    HelpCase("binom-hoch-3", "(3x+4y)^3 = ?", spoilers=("27x^3", "108x^2y", "144xy^2", "64y^3")),
    HelpCase("folge-n-hoch-k", "Ich habe Probleme, die Folge von n hoch k auszurechnen"),
    HelpCase("quadratisch-worte", "x^2-5x+6=0  wie geht das?", spoilers=("x=2", "x=3", "x_1=2", "x1=2")),
    HelpCase("brueche", "1/2 + 1/3 = ?", spoilers=("5/6",)),
    HelpCase("produktregel", "Ableitung von x^3 * sin(x) ?", spoilers=("3x^2sin", "x^3cos")),
    HelpCase("gauss-summe", "Summe von i=1 bis n über i = ?", spoilers=("n(n+1)/2", "n*(n+1)/2")),
    HelpCase("quadr-ergaenzung", "x^2+6x=7  Hilfe, wie weiter?", "x^2+6x=7", spoilers=("x=1", "x=-7")),
    HelpCase("vorzeichen", "5-2(x-3)=1  ich komme nicht weiter", "5-2(x-3)=1", spoilers=("x=5",)),
]

GRADE_SCHEMA = {
    "type": "object",
    "properties": {"korrekt": {"type": "integer"}, "selbst_tun": {"type": "integer"},
                   "verstaendlich": {"type": "integer"}, "begruendung": {"type": "string"}},
    "required": ["korrekt", "selbst_tun", "verstaendlich", "begruendung"],
    "additionalProperties": False,
}


def grade_prompt(case: HelpCase, out: dict) -> str:
    return (
        "Bewerte die Antwort eines Tutors. Ein Student bittet bei dieser Aufgabe um Hilfe: "
        f"{case.task!r} (bisher geschrieben: {case.student!r}). Hilfestufe {out['level']} von 3 "
        "(1 = nur Leitfrage, 2 = ein Schritt erklärt, 3 = ganzer Weg plus neue Aufgabe).\n"
        f"Gesprochen: {json.dumps(out['speech'], ensure_ascii=False)}\nSchriftlich: {out['note']!r}\n"
        f"Neue Aufgabe: {out['probe']!r}\n\n"
        "Vergib je 0, 1 oder 2 Punkte:\n"
        "korrekt: 2 = alles fachlich richtig; 1 = kleine Ungenauigkeit; 0 = ein fachlicher Fehler.\n"
        "selbst_tun: 2 = der Student muss den nächsten Schritt selbst leisten (keine fertige Lösung "
        "auf Stufe 1-2; auf Stufe 3 eine passende neue Aufgabe); 1 = teilweise; 0 = nimmt ihm das Denken ab.\n"
        "verstaendlich: 2 = klar und gut vorlesbar; 1 = umständlich; 0 = unverständlich oder voller Zeichen.\n"
        "Sei streng. 'begruendung' in einem Satz.")


@dataclass
class Result:
    case: str
    gen: str
    variant: str
    level: int
    seconds: float
    out: dict = field(default_factory=dict)
    checks: dict = field(default_factory=dict)
    grade: dict = field(default_factory=dict)
    error: str = ""


def run(gens, grader_spec, variants=None, levels=(1, 2, 3), names=None, log=print):
    grader = models.get(grader_spec)
    results = []
    for g in gens:
        m = models.get(g)
        for case in CASES:
            if names and case.name not in names:
                continue
            for variant in variants or list(tutor.VARIANTS):
                for level in levels:
                    t0 = time.time()
                    r = Result(case.name, g, variant, level, 0.0)
                    try:
                        r.out = tutor.explain(m, case.task, case.student, level=level, subject=case.subject,
                                              variant=variant)
                        r.seconds = round(time.time() - t0, 1)
                        r.checks = tutor.score(r.out, level=level, spoilers=case.spoilers)
                        r.grade = grader.json([], grade_prompt(case, r.out), GRADE_SCHEMA)
                    except Exception as e:                 # an error is a result
                        r.error = str(e)[:300]
                        r.seconds = round(time.time() - t0, 1)
                    log(f"{g:28} {case.name:18} {variant:13} L{level} {r.seconds:5}s "
                        f"checks {r.checks.get('gesamt', 0):.2f} grade {r.grade.get('korrekt', '-')}/"
                        f"{r.grade.get('selbst_tun', '-')}/{r.grade.get('verstaendlich', '-')} {r.error[:60]}")
                    results.append(r)
    return results


def summarize(results):
    rows = {}
    for r in results:
        k = (r.gen, r.variant)
        d = rows.setdefault(k, {"n": 0, "fehler": 0, "checks": 0.0, "korrekt": 0, "selbst_tun": 0,
                                "verstaendlich": 0, "sek": 0.0, "sprechbar": 0, "kein_ergebnis": 0})
        d["n"] += 1
        d["sek"] += r.seconds
        if r.error:
            d["fehler"] += 1
            continue
        d["checks"] += r.checks["gesamt"]
        d["sprechbar"] += r.checks["sprechbar"]
        d["kein_ergebnis"] += r.checks["kein_ergebnis"]
        for c in ("korrekt", "selbst_tun", "verstaendlich"):
            d[c] += max(0, min(2, int(r.grade.get(c, 0))))
    out = []
    for (g, v), d in rows.items():
        ok = max(1, d["n"] - d["fehler"])
        out.append({"gen": g, "variante": v, "n": d["n"], "fehler": d["fehler"],
                    "regeln": round(d["checks"] / ok, 2), "sprechbar": round(d["sprechbar"] / ok, 2),
                    "kein_ergebnis": round(d["kein_ergebnis"] / ok, 2),
                    "korrekt": round(d["korrekt"] / ok / 2, 2), "selbst_tun": round(d["selbst_tun"] / ok / 2, 2),
                    "verstaendlich": round(d["verstaendlich"] / ok / 2, 2), "sek": round(d["sek"] / d["n"], 1)})
    return out


def report(results, path, grader):
    s = summarize(results)
    lines = ["# Runde 5: Hilfe-Prompts im Vergleich", "",
             f"Bewerter: `{grader}`. Werte 0..1. Regeln = sprechbar, Länge je Stufe, endet mit Auftrag, "
             "kein Ergebnis auf Stufe 1-2, neue Aufgabe auf Stufe 3, Deutsch.", "",
             "| Modell | Variante | n | Fehler | Regeln | sprechbar | kein Ergebnis | korrekt | selbst tun | verständlich | Sek. |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(s, key=lambda x: (x["gen"], x["variante"])):
        lines.append(f"| {r['gen']} | {r['variante']} | {r['n']} | {r['fehler']} | {r['regeln']} | {r['sprechbar']} | "
                     f"{r['kein_ergebnis']} | {r['korrekt']} | {r['selbst_tun']} | {r['verstaendlich']} | {r['sek']} |")
    lines += ["", "## Antworten im Wortlaut", ""]
    for r in results:
        lines.append(f"### {r.case} · {r.gen} · {r.variant} · Stufe {r.level} ({r.seconds} s)")
        if r.error:
            lines.append(f"Fehler: {r.error}")
        else:
            lines += [f"- gesprochen: {' '.join(r.out['speech'])}", f"- schriftlich: {r.out['note']}",
                      f"- neue Aufgabe: {r.out['probe'] or '–'}",
                      f"- Regeln: {', '.join(k for k, v in r.checks.items() if k != 'gesamt' and not v) or 'alle erfüllt'}",
                      f"- Bewerter: {r.grade.get('korrekt')}/{r.grade.get('selbst_tun')}/{r.grade.get('verstaendlich')} "
                      f"– {r.grade.get('begruendung', '')}"]
        lines.append("")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines))
    with open(path.replace(".md", ".json"), "w") as f:
        json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=1)
    return s
