# Messstand: die Simulationsergebnisse als Seite

Live: https://claude.ai/artifact/E8dSM6CCWLxGSG11mGBGQE (privat, bis sie geteilt wird)

| Datei | Inhalt |
|---|---|
| `index.html` | Quelltext der Seite: Kennzahlen, Verlauf über die Runden, Wartezeiten, Vergleich aller Lesewege, echte Seiten, Befunde, Vorschläge aus ML- und AI-Engineering-Sicht |
| `data/eval_lines.json` | jede simulierte Zeile: Runde, Leseweg, Bewertung, Szenario, erwartet, gelesen als, Lesequalität, Ergebnis, Box-IoU |
| `data/eval_timing.json` | Dauer jeder Agentenrunde |
| `data/eval_help.json` | Runde 5: jede Tutor-Antwort mit Regelprüfung und Bewerterpunkten |
| `data/eval_pen.json` | Runde 4/7: Prüfstandsfälle des Stiftwegs |
| `data/eval_chaos.json` | Runde 7: Seiten-, Notizbuch- und Ordnerwechsel |

`index.html` ist kein eigenständiges HTML: Die Seite läuft im Dashboard-Typ von claude.ai, der die
beiden Datensätze (`zeilen`, `runden`) lädt und die Funktionen `dash.calc(...)` ausführt. Hier liegt
sie als nachvollziehbarer Stand neben den Daten, aus denen sie rechnet.

Daten neu erzeugen (nach einem Simulationslauf, siehe `docs/SIMULATION.md`):

```bash
python tools/export_eval.py /tmp/inkp      # schreibt docs/messstand/data/
```

Stand: 24.10.2026 morgens, Runden 1–7.
