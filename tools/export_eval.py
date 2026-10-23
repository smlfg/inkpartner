"""Turn the simulation reports into the two data files of the Messstand page (docs/messstand/data).

    python tools/export_eval.py [BASE]      BASE holds sim-out-r1 .. sim-out-r3-gemini and real/truth.json
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
rounds = [("Runde 1", "sim-out-r1"), ("Runde 2", "sim-out-r2"), ("Runde 3", "sim-out-r3"),
          ("Runde 3", "sim-out-r3-real"), ("Runde 3", "sim-out-r3-gemini")]
lines, timing = [], []
for name, folder in rounds:
    path = os.path.join(base, folder, "REPORT.json")
    if not os.path.exists(path):
        continue
    # Runde 1 was scored with the old scoring: score it again. Later rounds were scored live, with
    # the true ink boxes (needed for the box IoU), so their saved lines are used as they are.
    runs = sim.rescore(path, truth) if name == "Runde 1" else [sim.Run(**d) for d in json.load(open(path))]
    for run in runs:
        reader, judge = run.config.split(" | judge ")
        for l in run.lines:
            lines.append({"runde": name, "leseweg": reader, "bewertung": judge, "szenario": run.scenario,
                          "echt": run.scenario.startswith("echt-"), "zeile": l["text"], "erwartet": l["expect"],
                          "gelesen_als": l["read_as"], "lese_score": l["read_score"], "ergebnis": l["outcome"],
                          "box_iou": l.get("box_iou")})
        for rd in run.rounds:
            timing.append({"runde": name, "leseweg": reader, "bewertung": judge, "szenario": run.scenario,
                           "nach_zeile": rd["after_line"] + 1, "sekunden": rd["seconds"]})
os.makedirs(out, exist_ok=True)
json.dump(lines, open(os.path.join(out, "eval_lines.json"), "w"), ensure_ascii=False)
json.dump(timing, open(os.path.join(out, "eval_timing.json"), "w"), ensure_ascii=False)
print(len(lines), "line rows,", len(timing), "timing rows")
