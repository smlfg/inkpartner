# Selbst testen (Stand 24.10.)

## Vorher

1. Tablet am Kabel, Notizen-App offen, am besten das Notizbuch **Inkpartnertest**.
2. Sieh nach, ob auf der Seite nichts Fremdes steht. Dann die Sperre lösen:
   `rm ~/.cache/inkpartner/STOP`
   Solange die Datei da ist, schreibt der Agent nichts.
3. Mac nicht stumm, wenn du die Erklärungen hören willst. Ist er stumm, bleibt er stumm.

## Starten (auf dem Mac)

```bash
cd /tmp/inkp/ip3            # oder dein Klon von smlfg/inkpartner
PYTHONPATH=src ../venv/bin/python -m inkpartner watch --model ollama:qwen3.6:35b-a3b
# schneller, aus der Cloud:    --model minimax:MiniMax-M3
# nur Audiodateien statt Ton:  --speak file      ganz ohne Sprache: --speak off
```

Beenden mit Ctrl-C. Was der Agent tut, steht im Terminal.

## Was du ausprobieren kannst

| Du schreibst | Was passieren sollte |
|---|---|
| eine Rechnung mit Fehler, z. B. `3(x+2)=15` und darunter `3x+2=15` | nach der Schreibpause ein Kreis um die falsche Zeile |
| richtige Schritte | Haken |
| `(3x+4y)^3 = ?` | Stufe 1: kurzer schriftlicher Hinweis und eine gesprochene **Leitfrage**, keine Lösung |
| noch einmal ein `?` oder „Hilfe“ unter dieselbe Aufgabe | Stufe 2: der eine Schritt wird erklärt, dann sollst du ihn selbst schreiben |
| ein drittes Mal | Stufe 3: ganze Erklärung (bis zehn Sätze) und eine **neue ähnliche Aufgabe** auf dem Papier |
| du wechselst die Seite, bevor der Agent reagiert hat | nichts auf der fremden Seite; die Rückmeldung kommt, wenn du zurückkommst |
| du zoomst oder scrollst | der Agent misst die Ansicht aus dem Vorschaubild; erst ein kleiner Probestrich, dann der Rest |
| Code, ein neuronales Netz, BWL-Begriffe | wird gelesen und bewertet, aber schwächer gemessen als Mathe (Runde 6) |
| auf einem PDF-Aufgabenblatt | die gedruckte Aufgabe wird mitgelesen und nie markiert (Runde 7, am Gerät noch nicht gemessen) |

## Warum die Hilfe in Stufen kommt

Aus deiner eigenen Auswertung (Mail an Prof. Windberger, 18.09.): Erklärungen und Zusammenfassungen
fühlten sich produktiv an, ersetzten aber das selbstständige Lösen; Wiedererkennen wurde mit
sicherem Abruf verwechselt. Ein Tutor, der beim ersten „?“ zehn Sätze vorliest, wiederholt genau
das. Deshalb fragt er zuerst, erklärt erst auf Nachfrage und gibt nach jeder vollen Erklärung eine
neue Aufgabe, die du allein rechnest.

Wenn dir Stufe 1 zu knapp ist: einfach noch einmal fragen. Das ist so gewollt.

## Rückmeldung an mich

Am hilfreichsten: welche Seite, was du geschrieben hast, was der Agent getan hat, was du erwartet
hättest. Ein Foto der Seite reicht. Die Wächter-Ausgabe im Terminal hilft beim Nachvollziehen.

## Was nicht belegt ist

- Kein Stifttest am Gerät seit den neuen Prüfungen: Die Sperre war die ganze Nacht gesetzt. Der
  erste Lauf heute ist also der erste echte Test von Viewport und Probestrich.
- Ob der Probestrich über der Werkzeugleiste Werkzeuge umschaltet.
- Wie lange die Notizen-App zum Speichern braucht (Wartezeit zwischen Probestrich und Rest).
- PDF-Lage auf der Seite (eingepasst und zentriert ist eine Annahme).
