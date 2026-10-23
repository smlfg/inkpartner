"""What may be said aloud: natural language only.

Formulas, code, symbols and file paths are written, never spoken (Samuel's rule; HAI Voice Builder
holds the full rule set). This is the last gate before a TTS engine - it refuses rather than reads.
"""
from __future__ import annotations

import re

_FORBIDDEN = [
    re.compile(r"[=^_{}\\<>|`$]"),             # formula / markup / code characters
    re.compile(r"\b\d+\s*[+\-*/·×:]\s*\d+"),  # arithmetic
    re.compile(r"[A-Za-z0-9_.-]*/[A-Za-z0-9_./-]+"),  # paths, URLs
    re.compile(r"\b\w+\(\w*\)"),              # f(x), call()
    re.compile(r"\b[a-z]\d\b|\b\d[a-z]\b"),   # 3x, x2
]


def speakable(text: str) -> bool:
    t = text.strip()
    return bool(t) and len(t) <= 200 and not any(p.search(t) for p in _FORBIDDEN)
