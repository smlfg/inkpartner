# Wie wird eine Seite gelesen? Die bisherigen Varianten im Vergleich

Stand 2026-10-23. Quellen sind die Repos `algebra-agent`, `algebra-agent-htr-mac`, `penecho` und
`rm-drill-mac` (Code und Doku gelesen) sowie die Codex-Sitzung vom 23.10. für `pur` und `underline`.
Diese beiden Repos sind nicht auf GitHub und wurden hier **nicht selbst geprüft**.

## Lesen: Handschrift → etwas, worauf der Agent zeigen kann

| # | Variante | Wo | Was das Modell sieht | Wer trennt Zeilen/Elemente | Stand laut Doku |
|---|---|---|---|---|---|
| 1 | **A – Geometrische Zeilen** | `algebra-agent` `recognize.py` | je Zeile ein gerendertes PNG | Python (Nähe der Striche) | Mathe-Standard. Schräge Handschrift ließ 8 Zeilen zu 4 verschmelzen (Gerätetest 20.10.) |
| 2 | **B – Ganze Seite** | `algebra-agent` `recognize_whole.py` | die ganze Seite als ein Bild | das Modell, mit eigener Box als Anker | **entschieden 21.10.** für Prosa und Diagramme |
| 3 | **C – Hybrid** | `algebra-agent` `tools/ab_recognize.py` | ganze Seite mit eingezeichneten Trennlinien | Modell, Geometrie als Vorlage | nur noch Messwerkzeug |
| 4 | **Lokal, zwei Modelle** | `algebra-agent-htr-mac` `recognize_proto.py` | Zeilen-PNG an zwei Ollama-Modelle (qwen3.6, gemma4) | Python | Prototyp. Nur wenn beide übereinstimmen, gilt die Zeile als sicher |
| 5 | **Striche als Text** | `algebra-agent-htr-mac` `stroke_llm.py` | Koordinatenlisten als Text, kein Bild | – | **verworfen**: halluziniert (SYSTEMS.md) |
| 6 | **pur** | `~/…/Remarkable/pur` | ganze Seite, halbe Auflösung, plus getippter Text aus der Datei | Modell | Einzelpfad `.rm → LLM → .rm` ohne Tutor-Logik |
| 7 | **underline** | `~/…/Remarkable/underline` | Übersicht mit Zeilennummern **und** Zeilenausschnitte | Python + Modell | eigener Parser, kennt nur die Ebene `Underline Agent` |
| 8 | **rm-drill** | Skill + `rm-drill-mac` | gerenderte neue Striche, gelesen vom Agenten im Chat | der Chat-Agent | Abfrage-Schleife mit Sprachausgabe, am 21.10. benutzt |

## Was dabei auffällt

1. **Fünf Parser für dasselbe Format.** Alle nutzen `rmscene`, aber jedes Projekt baut eigene
   Seitendaten. Die Agentenebenen heißen verschieden (`PenEcho Agent`, `Underline Agent`). Jedes
   Projekt hält deshalb die Tinte des anderen für deine Schrift. `inkpartner` zählt alle bekannten
   Agentenebenen als Agententinte.
2. **Lesen und Urteilen sind fast überall verklebt.** Wer liest, entscheidet oft gleich mit, was
   gezeichnet wird. Deshalb gibt es heute fünf Darstellungsvarianten, aber „keine einzige regelt, was
   ein Hinweis *sagt*" (Notion, 20.10.).
3. **Nur Mathematik hat einen deterministischen Prüfer** (`stepcheck`). Die anderen Fächer hängen ganz
   am Modell. Das ist richtig so, aber dann müssen die Regeln (nie grün bei Unsicherheit, kein
   Lösungsverrat) außerhalb des Modells stehen.
4. **Zeilen sind die falsche Einheit für Diagramme.** Ein neuronales Netz hat Knoten und Kanten, keine
   Zeilen. Variante B hat dafür schon die „Element-Lesart für Diagramme" bekommen.

## Was inkpartner davon übernimmt und was es anders macht

| | übernommen | anders |
|---|---|---|
| Lesen | Variante B: ganze Seite, Modell liefert Boxen | Die Einheit heißt **Element** statt Zeile: Knoten, Kante, Code-Zeile, Kasten |
| Prüfen | sympy statt Modell, wo möglich (wie `stepcheck`) | Der Prüfer **überstimmt** das Modell. Belegte Schritte bekommen ihren Haken automatisch |
| Urteilen | Hinweisregeln aus `feedback.py` (kurz, deutsch, kein Verrat) | **Fachprofile** statt Fachcode. Die Farbe folgt dem Urteil, nicht dem Modell |
| Zeichnen | Agentenebene, Originalbytes bleiben (`rm_page.py`) | **Ein Vokabular** aus 7 Zeichen für alle Fächer, Platzsuche, die nie blockiert |
| Zustellen | – | Rückprüfung mit drei Ergebnissen, Wiederholung, Circuit Breaker, Verwerfen veralteter Hinweise |

## Offene Messungen, bevor man sich festlegt

- Variante 1 gegen 2 **auf deiner echten Mathe-Handschrift** (die HTR-Metrik in
  `algebra-agent/docs/HTR-METRIK.md` ist das Werkzeug). Für Mathe könnte A weiter besser sein.
  `inkpartner` kann dann trotzdem die Elemente von A übernehmen, der Elementvertrag erlaubt das.
- Variante 4 (lokal auf dem M3 Max) als Fallback ohne Netz und ohne Kosten.
