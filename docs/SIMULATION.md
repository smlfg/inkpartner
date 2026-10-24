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
| `vlm:<modell>` | die ganze Seite als ein Bild (auch `vlm:minimax:MiniMax-M3.1-Flash`, Cloud) |
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

## Runde 4: Zurückschreiben (24.10.)

Kein Modell, nur der Rückweg: eine feste Seite, feste Zeichen, ein simulierter Bildschirm mit Zoom,
Scrollen und **veraltetem Vorschaubild** (du hast gescrollt, ohne zu schreiben: keine Speicherung,
kein neues Bild). `python -m inkpartner pensim`.

Ablauf (`penpath.py`): Ansicht aus dem Vorschaubild schätzen → ragt ein Zeichen aus dem Bildschirm,
wartet es → **Probestrich** (der Strich mit dem meisten freien Papier drumherum) → Seite zurücklesen,
messen wo er gelandet ist → passt er auf 8 px, folgt der Rest, nach der Messung ausgerichtet;
sonst Stopp, und die Messung korrigiert den nächsten Versuch.

| Kennzahl | Ziel | Messung |
|---|---|---|
| richtige Entscheidung (zustellen / warten) | 100 % | 13 von 13 |
| zugestellt, wo zustellbar | ≥ 95 % | 11 von 11 |
| Abweichung der Zeichen | ≤ 8 px | 1,1 px im Mittel |
| Streustriche auf deiner Schrift | 0 | 0 |
| Streustriche insgesamt | so wenig wie möglich | 6, je einer pro veraltetem Bild |

| Befund | Ursache | Behoben durch |
|---|---|---|
| Zoom 1,5 und 0,8: Zeichen 6–14 px daneben | Ansicht nur grob geschätzt (ein Maskenpixel = 8 Bildschirmpixel) | Feinsuche im vollen Vorschaubild, Maßstab in 0,0025-Schritten |
| kleine Restabweichung nach gutem Probestrich | Schätzung nie ganz genau | der Rest wird nach der Messung des Probestrichs ausgerichtet |
| veraltetes Bild: ganze Notiz wäre 150–340 px daneben gelandet | Vorschaubild zeigt die alte Ansicht | Probestrich zuerst; ein kleiner Streustrich statt einer falschen Notiz |
| Probestrich könnte auf deiner Schrift landen | Probe war einfach der kleinste Strich | Probe = Strich mit dem meisten freien Papier drumherum |
| eigene Stiftstriche würden beim nächsten Lesen als deine Schrift gelesen | Stiftweg schreibt in deine Ebene | der Wächter merkt sich jeden eigenen Strich und liest ihn als Agententinte |

**Nicht belegt:** Wie schnell der Notizen-App speichert (Wartezeit zwischen Probe und Rest), ob
Stiftsignale über der Werkzeugleiste Werkzeuge umschalten, und wie oft das Vorschaubild in echt
veraltet ist. Das klären die Gerätetests (`python -m inkpartner pentest`).

## Runde 5: Hilfe in Stufen (24.10.)

`python -m inkpartner tutoreval --gen ollama:qwen3.6:35b-a3b --grader ollama:gemma4:26b`. 9 Hilfe-Fälle
(darunter dein Beispiel „Folge n hoch k“ und das Schlangenmuster aus der Vorlesung vom 16.10.) ×
3 Stufen × 3 Prompt-Varianten. Regeln deterministisch, Fachlichkeit und „selbst tun“ von einem
Bewerter aus einer anderen Modellfamilie (gemma4; MiniMax-M3, solange sein Zugang hielt).

| Variante (qwen3.6) | korrekt | selbst tun | verständlich | sprechbar | kein Ergebnis verraten |
|---|---|---|---|---|---|
| plain: bis zu zehn Sätze erklären | 0,99 | **0,06** | 1,00 | 0,44 | 0,63 |
| ladder: Leitfrage → ein Schritt → Erklärung + neue Aufgabe | 0,89 | 0,80 | 0,96 | 0,41 | 0,85 |
| ladder+words: dazu Mathematik in Worten | 0,84 | **0,81** | 0,94 | **1,00** | **1,00** |

Erklären ist fachlich fast immer richtig, nimmt aber das Denken ab, genau das Muster aus deiner
eigenen Auswertung. Der Preis der Stufen: etwas weniger Korrektheit. Danach geändert: Stufe 1
fragt, wenn unklar ist, was gemeint ist; Stufe 2 behauptet nichts, was nicht auf dem Blatt steht.
Auf den vier schwersten Fällen: korrekt 0,71 → 0,92, selbst tun 0,77 → 0,92 (nur gemma als Bewerter).
Die Bewerter waren sich bei 33 von 52 doppelt bewerteten Antworten in allen drei Punkten einig.

## Runde 6: andere Fächer (24.10.)

15 Szenarien: Code (Basisfall, Ganzzahldivision, Laufzeit, Schlangenmuster aus der Vorlesung),
BWL, Projektmanagement, gezeichnete neuronale Netze und Graphen. `--scenario subjects`.

| Leser und Bewerter | Treffer (nötig) | kritisch | verpasst |
|---|---|---|---|
| qwen3.6 | 20 % | 0 | 8 |
| qwen3.6 mit „Fehler heißen wrong“ (verworfen) | 60 % | **5** | 4 |
| gemma4 | 60 % | 4 | 1 |
| MiniMax-M3 | 60 % | 1 | 1 |

Gelesen wird fast alles richtig (0,87). qwen3.6 schlug für Fehler „help“ vor, das die Regel verwirft.
Die Prompt-Korrektur brachte Treffer, aber falsches Rot auf halbfertigem Code und auf
„Meilenstein: Dauer 0“: verworfen, weil ein falsches Rot schwerer wiegt als ein verpasster Fehler.
Code zuverlässig zu beurteilen braucht einen eigenen Prüfer (Schnipsel ausführen), wie sympy für Mathe.

## Runde 7: Chaos, PDF, echte Seiten neu (24.10.)

| Messung | vorher | nachher | durch |
|---|---|---|---|
| PDF, MiniMax-M3: kritische Fehler | 3 | 1 | Urteil nur, wenn eine Aufgabe auf der Seite steht |
| Fächer, MiniMax-M3: ungefragt | 3 | 1 | kein Urteil über Zeichnungsteile ohne Text |
| echte Seiten, qwen3.6: kritische Fehler | 3 | 2 | nichts widerrufen, solange die Tinte gleich bleibt |
| Leseweg `lines`: gelesen | 0,65 | 0,92 | Zeilentrennung ohne i-Punkt-Effekt |
| Chaos: Reaktionen verloren | 1 von 5 | 0 von 5 | Nachliefern bei Rückkehr auf die Seite |
| Zurückschreiben inkl. Vorlagen und PDF | – | 18/18 richtig, 0 auf deiner Schrift | Runde 4 |

Echte Seiten mit MiniMax-M3: 8 kritische Fehler (künstliche Schrift: 0). Deine Handschrift ist der
eigentliche Prüfstein; hier ist qwen3.6 lokal das beste Modell. Ohne die gedruckte Aufgabe schweigt
der Agent jetzt; das zählt als „verpasst“, ist aber ohne Aufgabe das richtige Verhalten.

**Nicht gültig:** MiniMax-M3.1-Flash auf echten Seiten (abgelaufener Zugang, 9 Fehler). Der Zugang
über die MiniMax-Code-CLI hält etwa eine Stunde; für verlässliche Läufe braucht es einen API-Schlüssel.
