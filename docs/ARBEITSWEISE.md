# Arbeitsweise in inkpartner: vom Fehlversuch zur Messung

Wie dieses Repo entstanden ist, als nachvollziehbare Abfolge. Die allgemeine Fassung für andere
Projekte steht in [METHODE.md](METHODE.md).

## 1. Fehlversuche auswerten statt neu anfangen

Vor inkpartner gab es acht Wege, eine Seite zu lesen, und mehrere Wege zurückzuschreiben (Übersicht:
[VERGLEICH.md](VERGLEICH.md)). Keiner war „fertig“. Statt Variante neun zu bauen, wurde jeder Versuch
befragt: Was sollte er leisten, woran ist er gescheitert, was ist die Ursache, und welche Regel folgt
daraus? Das war die einstündige Grill-Me-Sitzung mit Codex und danach das Nachlesen in Notion, in
alten Claude-Sitzungen und auf dem Tablet.

| Fehlversuch | Ursache | Daraus wurde |
|---|---|---|
| Geometrische Zeilen verschmolzen 8 Zeilen zu 4 | schräge Handschrift | ganze Seite lesen, Boxen danach an die echte Tinte anpassen (`geometry.snap`) |
| Striche als Koordinatentext | das Modell halluziniert | verworfen, nicht wieder versuchen |
| Ein Modell entscheidet Grün | eine Lesung kann falsch sein | Grün nur bei sicherer Lesung und sympy-Beleg; `agree:` mit zwei Lesungen |
| Dateiweg mit Neustart | meldet dich ab | **harte Grenze**: Neustart nur als letzter Ausweg, 30 min Ruhe, höchstens stündlich |
| Virtueller Stift landete daneben | Zoom und Scrollen ignoriert | Schutzprüfungen und Not-Aus; Viewport aus dem Vorschaubild |
| Agent fragt bei Schreibfehlern nach | Verantwortung zurückgegeben | Eskalation ohne Rückfrage: neu versuchen, anderer Weg, Sprache, sonst warten |

Ergebnis dieser Phase sind keine Ideen, sondern **Grenzen**: Was nie passieren darf (Abmeldung,
fremde Striche in deiner Ebene, Löschen deiner Schrift), und was der Mensch merken soll (Rückmeldung
ohne Auslöser, klein, in 5–10 s, höchstens 20 s).

## 2. Erfolg messbar machen, bevor gebaut wird

| Kennzahl | Art | Ziel | Stand Runde 3 (qwen3.6, künstliche Schrift) |
|---|---|---|---|
| Treffer auf Zeilen, die eine Reaktion verlangen | Hauptziel | ≥ 90 % | 7 von 8 (der eine Fehlschlag ist ein Auswertungsfehler) |
| kritisch: falsches Grün oder falsches Rot | Schutzgrenze | 0 | 0 |
| ungefragte Hilfe | Schutzgrenze | 0 | 0 |
| Sekunden pro Runde | Kosten | ≤ 10, höchstens 20 | 7,2 |
| Box trifft die Zeile (IoU) | Qualität | ≥ 0,6 | 0,70 |
| Abmeldungen, fremde Striche in deiner Ebene | Schutzgrenze am Gerät | 0 | erzwungen durch `guards.py` |
| Rückgeprüfte Zustellung | am Gerät | ≥ 95 % | **nicht gemessen** |

Schutzgrenzen werden nicht gegen das Hauptziel verrechnet: Ein Lauf mit einem falschen Grün ist
schlechter als einer mit einem verpassten Fehler.

## 3. Prüfstand vor Gerät

Der Agent läuft unverändert gegen ein simuliertes Tablet ([SIMULATION.md](SIMULATION.md)):
künstliche Handschrift, deine echten Seiten als Wiedergabe, Wahrheit je Zeile, Wertung je Reaktion.
Das Gerät wird erst angefasst, wenn eine Änderung dort gemessen besser ist.

## 4. Schleife: eine Änderung, ein Lauf, die Befunde im Wortlaut lesen

| Runde | Befund | Ursache lag in |
|---|---|---|
| 1 | ungefragte Hilfe nach jeder ersten Zeile | Regel |
| 1 | Gekritzel als Wort gelesen | Lesen |
| 1 | echte Reaktionen nicht gezählt | **Auswertung** |
| 2 | Boxen trafen die Zeile nur zu 25 % | Lesen, behoben durch Geometrie |
| 2 | sympy urteilte über unsichere Lesungen | Regel |
| 3 | Gekritzel als verpasst gezählt, obwohl die Wellenlinie gezeichnet wurde | **Auswertung** |
| 4 | Zeichen 6–14 px daneben bei Zoom | Messung der Ansicht, behoben durch Feinsuche |
| 5 | zehn Sätze Erklärung: „selbst tun“ 0,06 | Prompt; Hilfe in Stufen: 0,81 |
| 6 | Fehler als „help“ vorgeschlagen, von der Regel verworfen | Modell; Prompt-Korrektur **verworfen** (5 falsche Rot) |
| 7 | falsches Grün ohne sichtbare Aufgabe | Regel |
| 7 | Grün, dann Rot an derselben Zeile | Lesen schwankt; Regel |
| 7 | i-Punkt verschmilzt Zeilen | Code (Zeilentrennung) |
| 7 | Chaos-Szenario meldete alles verloren | **Auswertung** (Schreibpause im Skript zu kurz) |
| 7 | MiniMax-Läufe ungültig | Zugang lief ab (Messumgebung) |

Jeder Befund wird einer Ursache zugeordnet: Modell, Regel oder Messung. Ein Teil der Fehler steckt
regelmäßig im Messen selbst. Deshalb werden die Runden im Wortlaut gelesen, nicht nur die Zahlen.

## 5. Stufen bis zum selbstständigen Betrieb

1. Simulation erfüllt alle Ziele.
2. Echte Seiten als Wiedergabe erfüllen sie.
3. Drei begleitete Gerätetests mit Rückprüfung, ohne Auslösen einer Schutzprüfung.
4. Erst dann läuft der Wächter allein.

Stand 24.10. morgens: Stufe 1 für Mathe erreicht, Stufe 2 (deine echten Seiten) noch 2 kritische Fehler, Stufen 3–4 offen: kein Gerätetest, die Sperre war die ganze Nacht gesetzt.

## Was in dieser Sitzung schiefging (und jetzt Regel ist)

- Ein Neustart über den Dateiweg hat dich abgemeldet. Ich hatte eine ruhige Seite mit einem
  ruhigen Menschen verwechselt.
- Ein Stiftstrich landete an falscher Stelle in deiner Ebene, weil ich den Zoom nicht kannte.
- Ich habe dich gefragt, statt selbst zu eskalieren.

Alle drei sind jetzt Code: `guards.py`, `viewport.py`, die Eskalation im `Watcher`.

Messergebnisse als Seite: [messstand/](messstand/README.md).
