# Lesen: von der Seite zu den Elementen

Der Watcher-Weg. Das Urteilen beginnt erst nach der Elementliste. Andere Leser (`lines`, `ocr`, `shot`, `agree`) gibt es zum Vergleich; der Watcher ruft `agent.read` auf.

```mermaid
flowchart TD
  tick[Tick] --> file[Datei hat sich gesetzt]
  tick --> pen[Stift pausiert, Datei noch alt]
  file --> fetch["SSH: .rm holen"]
  pen --> fetch
  pen --> live[neue Striche aus dem Stift]
  fetch --> decode["rmscene: Ebenen und Striche"]
  live --> decode
  decode --> own[eigene Marken als Agent markieren]
  own --> window[Fenster um die neue Schrift]
  pdf[PDF der Aufgabe, falls vorhanden] --> png
  window --> png["PNG, nur Nutzerstriche"]
  png --> model[Modell liest die ganze Seite]
  model --> snap[Boxen an die echten Striche]
  snap --> els["Elemente: Text, Art, Box, Sicherheit"]
```

`tick` liest die Seite, die sich gesetzt hat, oder früher aus dem Stift, wenn die App noch nicht gespeichert hat. `read_strokes` macht aus der `.rm`-Datei Striche in Seitenpixeln. Eigene Marken zählen als Agent und kommen nicht ins Bild. `focus` lässt nur das Fenster um die neue Schrift. Das Modell bekommt ein PNG und liefert die Elemente; `snap` zieht die Boxen auf die echten Striche.
