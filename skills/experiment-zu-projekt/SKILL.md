---
name: experiment-zu-projekt
description: Turn an AI/agent experiment into an evaluated, measurable project. Use when a project has had several failed or half-working attempts, when someone says "grill me", "auswerten", "evaluieren", "SMART", "professionell machen", or before building yet another prototype. Runs a post-mortem of the failed attempts, fixes one primary metric plus zero-guardrails, builds the test bench before the prototype, then iterates one change per measured run.
---

Follow the method below with the user. You do the work (reading old attempts, building the bench,
measuring); the user supplies goals, hard limits, ground truth and real trade-off decisions. Do not ask
what you can find out yourself. Write the results into the project's repo: a post-mortem table, a
project card, the bench, a findings table per round, and a page of results.

Kernsatz: **Erst messen können, dann bauen.** Wer nicht sagen kann, woran er Besserung erkennt,
probiert aus.

## Phase 0: Fehlversuche auswerten (Grill-Me)

Jeder bisherige Anlauf wird befragt, am besten von einem zweiten Agenten oder Menschen, der nachbohrt:

1. Was sollte der Versuch leisten, in einem Satz?
2. Woran genau ist er gescheitert? Beobachtung, nicht Vermutung.
3. Was ist die Ursache? So lange „warum“ fragen, bis eine Ursache dasteht, die man ändern kann.
4. Was folgt daraus: eine Grenze, eine Regel, ein Testfall oder „nie wieder versuchen“?

**Ergebnis:** eine Tabelle Fehlversuch → Ursache → Konsequenz und eine Liste harter Grenzen (was nie
passieren darf). Jeder Fehlversuch wird später ein Testfall.

## Phase 1: Erfolg festlegen (SMART)

| Frage | Beispiel |
|---|---|
| Was merkt der Mensch, wenn es funktioniert? | Rückmeldung erscheint ungefragt, in 5–10 s |
| **Hauptkennzahl** (eine!) | Trefferquote auf Fällen, die eine Reaktion verlangen, Ziel ≥ 90 % |
| **Schutzgrenzen** (müssen 0 bleiben, nie verrechnet) | falsches Grün; Abmeldung; Daten des Nutzers verändert |
| **Kosten** | Sekunden pro Durchlauf, Euro pro Tag, Quota |
| Bis wann, in welchem Umfang? | Stufe 1 bis Freitag auf 11 Szenarien |

Spezifisch, messbar, erreichbar, relevant, terminiert: Jede Kennzahl hat Zahl, Ziel und Messweg.

## Phase 2: Prüfstand vor Prototyp

1. **Testsatz:** künstliche Fälle für Breite, echte Fälle für Wahrheit. Jeder Fehlversuch aus Phase 0
   ist darin.
2. **Wahrheit je Fall:** was richtig wäre. Ohne Wahrheit keine Messung.
3. **Wertung:** feste Kategorien (Treffer, verpasst, kritisch, ungefragt …), nicht „sieht gut aus“.
4. **Simulation:** das echte System läuft gegen eine Attrappe der Umgebung. Das Produktivsystem und
   der Mensch werden nicht gestört.
5. **Grundlinie:** die einfachste denkbare Lösung zuerst messen. Sie ist der Maßstab.

## Phase 3: kleinster messbarer Prototyp

So wenig wie möglich, so dass der Prüfstand ihn messen kann. Riskante Aktionen (schreiben, senden,
löschen, neu starten) stehen hinter Schutzprüfungen mit Not-Aus, bevor sie zum ersten Mal laufen.

## Phase 4: Schleife

1. Eine Änderung, ein Lauf. Mehrere Änderungen auf einmal verraten nicht, was gewirkt hat.
2. Ergebnisse **im Wortlaut lesen**, nicht nur die Zahlen.
3. Jeden Befund einer Ursache zuordnen: Modell, Regel/Code oder **Messung**. Die Messung ist oft
   selbst falsch. Eine Zahl, die sich verbessert, weil der Zähler kaputt ist, ist kein Fortschritt.
4. Ursache beheben, nicht Symptom. In einer Befundtabelle festhalten.
5. Wiederholen, bis die Ziele erreicht sind oder klar ist, dass der Ansatz nicht trägt.

## Phase 5: Stufen in die Wirklichkeit

Simulation → echte Daten als Wiedergabe → begleiteter Einsatz (z. B. drei erfolgreiche Läufe) →
selbstständiger Betrieb. Jede Stufe hat ein Tor: die Kennzahlen aus Phase 1.

## Phase 6: Zeigen, was belegt ist

Eine Seite mit den Kennzahlen über die Runden, den Befunden und einer ehrlichen Tabelle „belegt /
nicht belegt“. Das macht aus dem Experiment etwas, das andere prüfen können.

## Rollen

- **Mensch:** Ziel, harte Grenzen, Wahrheit, Entscheidungen bei echten Zielkonflikten.
- **Agent:** bauen, messen, Befunde zuordnen, berichten. Er fragt nicht, was er selbst herausfinden
  kann.

## Warnzeichen: es ist noch eine Ausprobier-Sitzung

- Niemand kann die Hauptkennzahl nennen.
- „Hat geklappt“ beruht auf einem einzelnen Versuch.
- Es wird direkt am Produktivsystem getestet.
- Jeder neue Anlauf beginnt bei null, statt den letzten auszuwerten.
- Ein Modell wird gewechselt, ohne denselben Testsatz laufen zu lassen.

## Projektkarte (zum Kopieren)

```
Projekt:
Was der Mensch merkt, wenn es klappt:
Fehlversuche bisher (je: Ursache → Konsequenz):
Harte Grenzen:
Hauptkennzahl + Ziel:
Schutzgrenzen (= 0):
Kosten (Zeit, Geld, Quota) + Grenze:
Testsatz (künstlich / echt), Wahrheit woher:
Grundlinie:
Stufen + Tor je Stufe:
Stand (Datum, Runde, Zahlen):
```
