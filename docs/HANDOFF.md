# Übergabe – inkpartner, Stand 24.10.2026, 18:50

Für die nächste Session. Lies das hier zuerst, dann `README.md`, `docs/SIMULATION.md`,
`docs/ARBEITSWEISE.md`. Samuel: „Das Projekt ist mir eine Herzenssache – wie sonst soll ich mit
Agenten lernen, wenn nicht so.“

## Ziel (unverändert)

Samuel schreibt auf dem reMarkable Paper Pro. Der Agent liest mit, prüft und **schreibt in unter
15 s zurück**: Kreis bei Fehler, Haken bei Richtigem, kurze Notiz. Bei Fragen hilft er in Stufen,
gesprochen. Gilt für Mathe, Geometrie, Code, BWL, PM, Diagramme. Es muss rückwirkend gehen: Samuel
soll nicht extra zeichnen müssen, damit der Agent arbeiten kann.

## Harte Grenzen

- Nie aus dem Notizbuch werfen. Ein Neustart der Notizen-App meldet ab, nur als letzter Ausweg.
- Nichts von Samuels Schrift löschen. Muted bleibt muted. Gesprochen wird nur natürliche Sprache, keine Formeln.
- Bei Problemen nicht fragen, sondern selbst eskalieren. **Selbst nachprüfen**, nicht Samuel nachschauen
  lassen. Am 24.10. war er zu Recht genervt.
- Ein falsches Rot oder Grün wiegt schwerer als ein verpasster Fehler.

## Was am Gerät belegt funktioniert (24.10.)

| Teil | Beleg |
|---|---|
| Lesen + Urteilen | `2+2=5` als falsch erkannt. Lesen 1,9 s + Bewerten 2,3 s. Geometrie-Seite gelesen |
| Hilfe in Stufen, gesprochen | Pythagoras-/Sinussatz-Frage, Stufe 1 gesprochen. Samuel: „ich höre den Agent – das ist Erfolg“ |
| Stimme | Piper **Thorsten** (`~/.local/share/piper/de_DE-thorsten-high.onnx`), lokal auf dem M3 Max |
| Ansicht aus dem Stift | Stiftsignale (Bildschirm) gegen gespeicherte Striche (Seite): Maßstab 0,99, Scroll −1783 px exakt |
| Stift erzeugt Tinte | Selbsttest: Strich kam an, aber in Quick sheets **quer gehalten**, um 90° gedreht |
| Zeit Pause → Strich | ca. 8 s (3 s Pause + 5,2 s Lesen/Urteilen + 1,1 s Senden), Ziel unter 15 s |

**Noch NICHT belegt:** ein Kreis, der richtig ausgerichtet an der richtigen Stelle sitzt. Die
Drehung ist seit Commit `f8b6adc` eingebaut, der Live-Test steht aus.

## Die 7 Gerätebefunde vom 24.10. (keine Simulation hätte sie gefunden)

1. **Das Vorschaubild zeigt den Seitenanfang**, nicht die gescrollte Ansicht. Daher kommt die Ansicht jetzt aus dem Stift (`viewport.from_pen`).
2. **Die App speichert Striche bis zu ~1 min verspätet** („Scene written to“ im Journal). Daher wird live aus dem Stift gelesen (`Tablet.live_strokes`, `Watcher._pen_review`), und bei gemessener Ansicht kommt kein Probestrich.
3. **Ein Notizbuch war seit gestern offen**, die Erkennung sah nur 12 h zurück. Jetzt: `journalctl -b` plus „Scene written to“ (`parse_open_page`).
4. **Der Tiefschlaf trennt USB** (10.11.99.1 weg, auch Tailscale `remarkable-ts` tot). Abhilfe: Kabel neu einstecken. TODO: Der Wächter soll das melden, etwa gesprochen, statt still Fehler zu loggen.
5. **Stiftsignale am Stück → „Timeout while waiting for penpoint“.** Jetzt im Takt, eine Meldung alle 2 ms (`penstream.reports`, `Tablet.send`).
6. **Das Tablet lag quer** (Quick sheets). `Viewport.turn` wird jetzt mitgemessen (komplexe Ähnlichkeit, Viertelumdrehung). Mindestens 2 Striche nötig.
7. **Hängende `cat /dev/input/event2|3`-Prozesse auf dem Tablet** nach Wächter-Neustarts. Aufräumen: `ssh remarkable 'killall cat'`. TODO: Lese-Prozesse sauber beenden.

## Sofort als Nächstes

1. **Live-Test Kreis.** Wächter starten (s. u.). Samuel schreibt `3 + 4 = 8` (≥ 3 Striche), Stift weg. **Selbst prüfen**: nach dem Speichern die Seite lesen (Strich in der Datei mit erwarteter bbox?), `journalctl -u xochitl` auf „penpoint“ durchsuchen.
2. Falls der Kreis falsch sitzt: Selbsttest-Skript `/tmp/inkp/selftest.py` (Strich an freier Stelle, danach auf Speichern warten, bbox vergleichen) mit einem **asymmetrischen L**, um Drehung und Spiegelung eindeutig zu sehen.
3. Rückwirkend ohne frischen Strich: gemerkte Ansicht (bis Fingerberührung, `event3`) funktioniert. Ganz ohne Stiftdaten bleibt nur der Probestrich. Der wartet aufs Speichern und ist langsam. Idee: eine Fingergeste als Scroll-Messung (Touch-Delta) statt Probestrich.
4. Wächter meldet Verbindungsverlust (Befund 4) und räumt Lese-Prozesse auf (Befund 7).
5. Geometrie-Simulation laufen lassen: `sim --scenario geometry` (6 Szenarien, noch nie gelaufen).

## Starten / Pfade (Mac `samuel-mbp`, per Desktop Commander)

```bash
cd /tmp/inkp/ip3 && git pull
pkill -f "inkpartner watch"; ssh remarkable 'killall cat'      # alte Leser weg
PYTHONPATH=src nohup ../venv/bin/python -u -m inkpartner watch --model ollama:qwen3.6:35b-a3b > /tmp/inkp/watch.log 2>&1 &
grep -v "Some data" /tmp/inkp/watch.log | tail                    # timing-Zeile zeigt read/judge/teach
```
- **`/tmp/inkp` überlebt keinen Mac-Neustart.** Gesichert (24.10.) nach
  `~/Projects/01_WORK/Remarkable/inkpartner-data/2026-10-24/`: alle `sim-out-*`, `real/` (Samuels
  echte Seiten + `truth.json`), Logs, Skripte. Die Geräte-Skripte liegen auch in `tools/device/`.
  Fehlt die venv: `python3 -m venv /tmp/inkp/venv && /tmp/inkp/venv/bin/pip install rmscene pillow numpy sympy pypdfium2`.
- Sperre/Not-Aus: `~/.cache/inkpartner/STOP` (am 24.10. gelöscht; legt sich bei R-FOREIGN neu an).
- Zustand pro Seite: `~/.cache/inkpartner/state.json` (delivered, own_sigs, verdicts, expected).
- Tablet: `ssh remarkable` (10.11.99.1, USB). Stift `event2`, Touch `event3`. Firmware 20261009.
- Modelle: qwen3.6:35b-a3b lokal (Ollama, keep_alive 60 min). MiniMax-M3 ist auf künstlicher
  Schrift gut, auf Samuels echter Schrift schlecht (8 statt 2 kritische Fehler). Der CLI-Token
  hält ~1 h; ein echter `MINIMAX_API_KEY` fehlt.
- Messstand-Seite: https://claude.ai/artifact/E8dSM6CCWLxGSG11mGBGQE (Runden 1–7).
- Skill zur Methode: `smlfg/HAI-skills-registry` → `skills/engineering/experiment-to-project`.

## Kontext zu Samuel (wichtig für den Ton)

- Seine eigene Analyse (Mail an Prof. Windberger, 18.09.): Lernaktivität ersetzte das selbstständige
  Lösen, Wiedererkennen wurde mit Können verwechselt. Deshalb fragt die Hilfe zuerst und erklärt
  erst auf Nachfrage (Runde 5: „selbst tun“ 0,06 → 0,81).
- Plaud-Tagesfazit 21.10.: Scope Creep, viele Tokens, Prüfungsvorbereitung (Grundlagen der
  Informatik) blieb liegen. Ziel ist, dass er **damit lernt**, nicht dass weiter gebaut wird.
  Echter Stoff zum Testen: Schlangenmuster/Raster aus der Vorlesung vom 16.10.
- Nach einem erfolgreichen Live-Test **nicht weiter ausbauen**, sondern zum Lernen übergeben.

## Commits dieser Session (Auswahl, `main`)

`645a05b` Ansicht aus dem Stift · `bd55792` live aus dem Stift lesen, gemerkte Ansicht, kein Probestrich
· `605fbb4` Stift im Takt · `f8b6adc` Drehung · `879b56b` Thorsten · `a318dce` Geometrie
· `9ef7a09` unter 15 s (Fokus, Takt) · `7ded872` Prompt-Rücknahme (Schutzgrenze) · Tests: 95 grün.
