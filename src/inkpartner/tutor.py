"""Help in steps, spoken as well as written - built on why exam preparation failed before.

Samuel's own analysis (mail to the programme director, 2026-09-18): lots of learning activity -
plans, explanations, summaries - that felt productive but replaced solving new tasks alone;
recognising and understanding were mistaken for secure recall; gaps showed only in a mock exam the
evening before. A tutor that reads out ten sentences of explanation at the first "?" repeats exactly
that pattern. So help comes as a ladder, and every explanation ends in work for the student:

    level 1   a guiding question and the rule to use (1-2 spoken sentences), never the result
    level 2   the one step he is stuck on, explained (3-5 sentences), then: "now you do it"
    level 3   the full explanation (up to 10 sentences), then a NEW similar task to solve alone

The level goes up only when he asks again about the same task. Speech is natural language only
(speech.py): formulas are said in words ("x hoch drei"), never read as symbols.
"""
from __future__ import annotations

import re

from . import speech

SENTENCES = {1: (1, 2), 2: (3, 5), 3: (5, 10)}

SCHEMA = {
    "type": "object",
    "properties": {
        "speech": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
        "probe": {"type": "string"},
    },
    "required": ["speech", "note", "probe"],
    "additionalProperties": False,
}

WORDS = ("Sprich Mathematik in Worten, nie als Zeichen: 'x hoch drei', 'a plus b in Klammern hoch drei', "
         "'Bruch eins durch n', 'Wurzel aus zwei', 'Summe von i gleich eins bis n'. Keine Gleichheits-, "
         "Hoch-, Klammer- oder Rechenzeichen und keine Ziffernfolgen mit Rechenzeichen im gesprochenen Text.")

LADDER = {
    1: ("Stufe 1 von 3. Gib NICHT die Lösung und NICHT den Rechenweg. Stelle eine Leitfrage, die ihn den "
        "nächsten Schritt selbst finden lässt, und nenne höchstens die Regel oder Formel, die er braucht. "
        "Ist unklar, was genau gefragt ist, frage zuerst danach, statt eine Aufgabe zu erfinden. "
        "Ein bis zwei gesprochene Sätze, der letzte ist eine Frage."),
    2: ("Stufe 2 von 3: er hat schon einmal gefragt. Erkläre genau den einen Schritt, an dem er hängt, "
        "konkret an seiner Aufgabe, aber rechne die Aufgabe nicht zu Ende. Drei bis fünf gesprochene Sätze; "
        "der letzte fordert ihn auf, diesen Schritt jetzt selbst aufzuschreiben. Behaupte nichts über "
        "seine Arbeit, was nicht auf dem Blatt steht."),
    3: ("Stufe 3 von 3: er hat zweimal gefragt. Erkläre den ganzen Lösungsweg verständlich in fünf bis "
        "zehn gesprochenen Sätzen. Danach eine NEUE, ähnliche Aufgabe in 'probe' (kurz, als Formel), die "
        "er ohne Hilfe lösen soll; der letzte Satz sagt ihm, dass er die neue Aufgabe allein rechnen soll."),
}

VARIANTS = {
    # the first idea, as asked for: explain it in up to ten sentences
    "plain": lambda task, student, level, subject: (
        f"Ein Student lernt {subject} auf Papier und braucht Hilfe bei: {task!r}. Was er bisher "
        f"geschrieben hat: {student!r}. Erkläre es ihm auf Deutsch in bis zu zehn Sätzen, die vorgelesen "
        "werden. 'note' ist ein kurzer schriftlicher Hinweis (höchstens 140 Zeichen), 'probe' leer."),
    # retrieval first: the ladder above
    "ladder": lambda task, student, level, subject: (
        f"Du bist ein Tutor. Ein Student lernt {subject} auf Papier (Prüfungsvorbereitung) und bittet um "
        f"Hilfe bei: {task!r}. Was er bisher geschrieben hat: {student!r}. Er versteht Erklärungen schnell, "
        "aber Wiedererkennen ist nicht Können: er muss selbst rechnen. " + LADDER[level] +
        " 'speech' sind die gesprochenen Sätze auf Deutsch. 'note' ist ein kurzer schriftlicher Hinweis für "
        "das Papier (höchstens 140 Zeichen, Formeln erlaubt, nie das Ergebnis). 'probe' ist leer außer auf "
        "Stufe 3."),
    # ladder plus how to say mathematics aloud
    "ladder+words": lambda task, student, level, subject: VARIANTS["ladder"](task, student, level, subject)
    + " " + WORDS,
}


def explain(model, task: str, student: str = "", *, level: int = 1, subject: str = "Mathematik",
            variant: str = "ladder+words") -> dict:
    level = max(1, min(3, level))
    out = model.json([], VARIANTS[variant](task, student, level, subject), SCHEMA)
    sents = [s.strip() for s in out.get("speech", []) if s and s.strip()]
    return {"speech": sents, "note": out.get("note", "").strip(), "probe": out.get("probe", "").strip(),
            "level": level, "variant": variant}


def say_ok(sentences: list[str]) -> list[str]:
    """Only the sentences that may be spoken; a formula sentence is dropped, not read out."""
    return [s for s in sentences if speech.speakable(s)]


def task_key(text: str) -> str:
    t = re.sub(r"(?i)\b(hilfe|wie geht das|ich verstehe|verstehe ich nicht|problem\w*|bitte)\b", "", text)
    return re.sub(r"[\s?!.,:=]+", "", t.lower())


# ------------------------------------------------------------------ scoring
def score(out: dict, *, level: int, spoilers: tuple[str, ...] = ()) -> dict:
    """Deterministic checks of one answer. A model grader adds correctness on top (tutoreval.py)."""
    sents = out["speech"]
    lo, hi = SENTENCES[level]
    spoken = " ".join(sents)
    norm = re.sub(r"\s", "", (spoken + " " + out["note"]).lower())
    checks = {
        "sprechbar": bool(sents) and all(speech.speakable(s) for s in sents),
        "laenge": lo <= len(sents) <= hi,
        "auftrag": bool(sents) and (sents[-1].rstrip().endswith("?") if level == 1 else
                                     bool(re.search(r"(?i)\b(du|dein|versuch|schreib|rechne|probier|jetzt)", sents[-1]))),
        "kein_ergebnis": level == 3 or not any(re.sub(r"\s", "", s.lower()) in norm for s in spoilers),
        "neue_aufgabe": (bool(out["probe"]) if level == 3 else True),
        "deutsch": bool(re.search(r"(?i)\b(der|die|das|und|ist|du|nicht|mit)\b", spoken)),
    }
    checks["gesamt"] = sum(checks.values()) / len(checks)
    return checks
