# Interaktionsregeln Mensch ↔ Agent auf dem reMarkable

Gesammelt aus Notion („PenEcho — Projektplanung", Stand 20.10.), dem PenEcho-Produktvertrag und der
Grill-Me-Sitzung mit Codex vom 23.10. Jede Regel nennt ihre Umsetzung hier oder sagt, dass sie fehlt.

| # | Regel | Quelle | Umsetzung |
|---|---|---|---|
| R1 | Deine Schrift wird nie gelöscht oder umgeschrieben | Notion DoD 4, Codex | `page.append_strokes`: Originalbytes bleiben Präfix (Test) |
| R2 | Agentenzeichen dürfen deine Schrift überlappen; Platzmangel darf das Schreiben nicht blockieren | Codex | `layout.place` fällt auf Überlappung zurück (Test) |
| R3 | Schwarz = du, grün = richtig, rot = falsch | Notion, Hardware-Entscheidung | Farbe folgt dem Urteil (`plan.VERDICT_COLOR`) |
| R4 | Grün darf auch „bis hierhin fehlerfrei" heißen | Codex | Haken für jeden von sympy belegten Schritt |
| R5 | Unsicheres wird nie grün; Unleserliches bekommt eine Wellenlinie | algebra-agent, Codex | `plan.validate` (Tests) |
| R6 | Der Agent kann sprechen, unterstreichen, abhaken und Text schreiben | Codex | `marks.py`; Sprache über `delivery.Outbox(speak=…)` |
| R7 | Nie vorrechnen, kleinste hilfreiche Hilfe | Notion, Produktvertrag | Profiltexte; **Lösungsverrat wird nicht maschinell geprüft** |
| R8 | Automatisch, ohne Auslöser; regelmäßig nachschauen, nur bei Bedarf reagieren | Codex (ersetzt „bewusst auslösen" aus Notion DoD 6) | **fehlt hier**, siehe Auslöser-Varianten in `algebra-agent/trigger` |
| R9 | Klein und inkrementell statt eines großen Wurfs; Ziel 5–10 s, 20 s akzeptabel | Codex | höchstens 3–4 Zeichen pro Runde; Latenz **nicht gemessen** |
| R10 | Die Oberfläche darf nie stoppen oder neu starten | Codex, Must-have | **nur über den virtuellen Stift erfüllbar**; nicht in diesem Repo |
| R11 | Erfolg heißt: auf der geöffneten Seite sichtbar | Codex | `verify.verify` nach jedem Schreiben; drei Ergebnisse |
| R12 | Fehler behebt der Agent selbst, er fragt dich nicht | Codex | `delivery.Outbox`: Wiederholung, Breaker (Tests) |
| R13 | Bei „unklar" nicht doppelt schreiben | Codex | erst zurücklesen, dann schreiben (Test) |
| R14 | Stumm bleibt stumm; Sprache nur nach Freigabe für die Sitzung | Codex | `speech_allowed=False` als Standard (Test) |
| R15 | Gesprochen wird nur natürliche Sprache: keine Formeln, kein Code, keine Pfade | Codex, HAI Voice Builder | `speech.speakable` (Test) |
| R16 | Veraltetes Feedback wird verworfen | Codex | `still_valid` vor jeder Zustellung (Test) |
| R17 | Der Agent reagiert nicht auf seine eigene Tinte | Codex, Trigger-Spec | Agentenebenen werden beim Lesen ausgelassen |
| R18 | Gilt für alle Fächer: Rechnen, Code auf Papier, Projektmanagement, neuronale Netze, Graphen | du, 23.10. | Fachprofile in `profiles.py` |

## Widerspruch, den du entscheiden musst

R8 (automatisch) widerspricht Notion DoD 6 und der Trigger-Spezifikation („Mensch entscheidet jederzeit,
wann der Agent reagiert"). In der Codex-Sitzung hast du dich für automatisch entschieden. Wenn das gilt,
sollten DoD 6 und die Trigger-Spec angepasst werden. Sonst arbeiten Agenten weiter gegen die alte Regel.
