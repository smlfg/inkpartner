# Simulation: reagiert der Agent, und wie?

Ein simulierter Schüler schreibt, ein simuliertes Tablet speichert, der **echte** Agent reagiert.
Das echte Tablet wird dabei nie angefasst. So lässt sich jede Änderung an Regeln, Lesewegen oder
Modellen messen, bevor sie an dein Gerät kommt.

## Ablauf je Szenario

1. Der Schüler schreibt eine Zeile. Das passiert entweder in handschriftähnlicher Schrift (Zittern,
   schräg nach unten, Hochzahlen hochgestellt) oder als Wiedergabe deiner echten Seite, Zeile für
   Zeile in der Reihenfolge, in der du geschrieben hast.
2. Der Wächter merkt die Änderung. Solange „geschrieben wird“, wartet er.
3. Nach der Schreibpause liest er die Seite, prüft mit sympy, bewertet mit dem Modell, wendet die
   Regeln an und zeichnet seine Zeichen in die Agentenebene der simulierten Seite.
4. Jede Reaktion wird gegen die Wahrheit des Szenarios gewertet.

| Ergebnis | Bedeutung |
|---|---|
| Treffer | die erwartete Reaktion: rot bei Fehler, Hilfe bei Frage, Wellenlinie bei Gekritzel |
| kritisch | falsches Grün auf einem Fehler oder falsches Rot auf einer richtigen Zeile |
| verpasst | keine passende Reaktion |
| teilweise | nur ein Hinweis, wo Rot oder Hilfe erwartet war |
| ungefragt | Hilfe oder Hinweis auf einer richtigen Zeile, obwohl niemand gefragt hat |
| Box trifft | Überlappung (IoU) der Elementbox mit der echten Zeile. Dort landen die Zeichen |

## Starten (auf dem Mac)

```bash
cd inkpartner
set -a; . ~/Projects/01_WORK/Remarkable/algebra-agent/.env; set +a   # nur für gemini:
PYTHONPATH=src python3 -m inkpartner sim --out sim-out \
  "vlm:ollama:qwen3.6:35b-a3b@ollama:qwen3.6:35b-a3b" \
  "agree:vlm:ollama:qwen3.6:35b-a3b+vlm:ollama:gemma4:26b@ollama:qwen3.6:35b-a3b" \
  "ocr:apple@ollama-text:gpt-oss:20b"
# echte Seiten dazu:   --real /pfad/truth.json   (Format: examples/real/truth.json)
# nur bestimmte Szenarien:   --scenario hilfe-binom-hoch-3
# gespeicherte Läufe neu werten:   --rescore sim-out/REPORT.json
```

Ein Lauf ist `LESEWEG@BEWERTUNG`.

| Leseweg | Was das Modell sieht |
|---|---|
| `vlm:<modell>` | die ganze Seite als ein Bild |
| `lines:<modell>` | geometrisch ausgeschnittene Zeilen |
| `ocr:tesseract`, `ocr:apple` | klassische Texterkennung, kein Modell |
| `agree:<A>+<B>` | zwei Lesungen, die übereinstimmen müssen |

Die Bewertung ist eine Modellkette. Mit `ollama-text:<modell>` bekommt ein reines Textmodell nur die
gelesenen Elemente, kein Bild.

Ergebnis: `REPORT.md` (Tabelle und jede Runde im Wortlaut), `REPORT.json`, ein PNG je Szenario mit
den Zeichen des Agenten.

## Was die Schleife schon gefunden hat (23.10.)

| Runde | Befund | Behoben durch |
|---|---|---|
| 1 | ungefragte Hilfe nach der ersten Zeile jeder Aufgabe | Regel: Hilfe nur, wenn die Seite fragt (`?`, Hilfe, Problem, versteh…) |
| 1 | `(z+x)^4 =` nicht prüfbar, Rot hing am Modell | Zeile mit `=`/`=>` am Ende = Ausdruck; sympy setzt den Kreis selbst |
| 1 | Gekritzel als „mwwv“ gelesen, als wäre es lesbar | `agree:`, zwei Lesungen; unleserlich → Wellenlinie per Regel |
| 1 | Modelle antworten in LaTeX (`z^{4x}`) | sympy liest geschweifte Klammern |
| 1 | Auswertung zählte echte Reaktionen nicht (Boxen daneben) | Zuordnung über den gelesenen Text; Box-Treffer als eigene Zahl |
