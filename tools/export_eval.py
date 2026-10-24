"""Turn the simulation reports into the data files of the Messstand page (docs/messstand/data).

    python tools/export_eval.py [BASE]      BASE holds the sim-out-* folders and real/truth.json
                                            (default /tmp/inkp, where the Mac runs keep them)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from inkpartner import sim  # noqa: E402

base = sys.argv[1] if len(sys.argv) > 1 else "/tmp/inkp"
out = os.path.join(HERE, "..", "docs", "messstand", "data")
truth = os.path.join(base, "real", "truth.json")
SUBJECTS = {s.name for s in sim.SUBJECT_SCENARIOS}

# (round label, folder). sim-out-r3-minimax-real is left out on purpose: 9 of its rounds failed on
# an expired MiniMax token (24.10.), so its numbers measure the login, not the agent.
ROUNDS = [("Runde 1", "sim-out-r1"), ("Runde 2", "sim-out-r2"), ("Runde 3", "sim-out-r3"),
          ("Runde 3", "sim-out-r3-real"), ("Runde 3", "sim-out-r3-gemini"), ("Runde 3", "sim-out-r3-minimax"),
          ("Runde 6", "sim-out-r6"), ("Runde 6", "sim-out-r6-minimax"),
          ("Runde 6b", "sim-out-r6-qwen-prompt"),
          ("Runde 7", "sim-out-r7-pdf"), ("Runde 7", "sim-out-r7-pdf-minimax"), ("Runde 7", "sim-out-r7-lines"),
          ("Runde 7", "sim-out-r7-real"), ("Runde 7", "sim-out-r7-real-minimax")]


def satz(scenario: str) -> str:
    if scenario.startswith("echt-"):
        return "echt"
    if scenario.startswith("pdf-"):
        return "pdf"
    return "faecher" if scenario in SUBJECTS else "mathe"


lines, timing = [], []
for name, folder in ROUNDS:
    path = os.path.join(base, folder, "REPORT.json")
    if not os.path.exists(path):
        continue
    # Runde 1 was scored with the old scoring: score it again. Later rounds were scored live, with
    # the true ink boxes (needed for the box IoU), so their saved lines are used as they are.
    runs = sim.rescore(path, truth) if name == "Runde 1" else [sim.Run(**d) for d in json.load(open(path))]
    for run in runs:
        reader, judge = run.config.split(" | judge ")
        for l in run.lines:
            lines.append({"runde": name, "satz": satz(run.scenario), "leseweg": reader, "bewertung": judge,
                          "szenario": run.scenario, "echt": run.scenario.startswith("echt-"),
                          "zeile": l["text"], "erwartet": l["expect"], "gelesen_als": l["read_as"],
                          "lese_score": l["read_score"], "ergebnis": l["outcome"], "box_iou": l.get("box_iou"),
                          "fehler": len(run.errors)})
        for rd in run.rounds:
            timing.append({"runde": name, "satz": satz(run.scenario), "leseweg": reader, "bewertung": judge,
                           "szenario": run.scenario, "nach_zeile": rd["after_line"] + 1, "sekunden": rd["seconds"]})

hilfe = []
for name, folder in (("Runde 5", "sim-out-r5"), ("Runde 5b", "sim-out-r5-check")):
    path = os.path.join(base, folder, "REPORT.json")
    if not os.path.exists(path):
        continue
    for r in json.load(open(path)):
        if r["error"]:
            continue                      # MiniMax answers lost to the expired token: not a result
        g = r["grade"]
        hilfe.append({"runde": name, "modell": r["gen"], "variante": r["variant"], "stufe": r["level"],
                      "fall": r["case"], "sek": r["seconds"], "regeln": r["checks"]["gesamt"],
                      "sprechbar": r["checks"]["sprechbar"], "kein_ergebnis": r["checks"]["kein_ergebnis"],
                      "korrekt": g.get("korrekt"), "selbst_tun": g.get("selbst_tun"),
                      "verstaendlich": g.get("verstaendlich"), "bewerter": len([1 for d in r["grades"].values()
                                                                               if "error" not in d]),
                      "gesprochen": " ".join(r["out"].get("speech", [])), "schriftlich": r["out"].get("note", "")})

pen = []
path = os.path.join(base, "sim-out-r7-pen", "REPORT.json")
if os.path.exists(path):
    for r in json.load(open(path)):
        pen.append({"fall": r["case"], "erwartet": r["expect"], "ergebnis": r["outcome"], "versuche": r["attempts"],
                    "abgelehnt": ", ".join(r["refusals"]), "abweichung_px": r["error_px"],
                    "streustriche": r["stray"], "auf_schrift": r["stray_on_ink"]})

chaos = []
path = os.path.join(base, "sim-out-r7-chaos", "REPORT.json")
if os.path.exists(path):
    for e in json.load(open(path))["expected"]:
        chaos.append({"seite": e["page"], "zeile": e["text"], "erwartet": e["expect"], "ergebnis": e["result"]})

os.makedirs(out, exist_ok=True)
for fname, data in (("eval_lines.json", lines), ("eval_timing.json", timing), ("eval_help.json", hilfe),
                    ("eval_pen.json", pen), ("eval_chaos.json", chaos)):
    json.dump(data, open(os.path.join(out, fname), "w"), ensure_ascii=False)
print(len(lines), "lines,", len(timing), "timing,", len(hilfe), "help,", len(pen), "pen,", len(chaos), "chaos")
