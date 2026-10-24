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


def shlex_quote(t: str) -> str:
    import shlex
    return shlex.quote(t)


class MacSpeaker:
    """Local voice on the Mac. mode 'play': `say`, but never when the Mac is muted (muted stays
    muted); mode 'file': only writes an audio file per utterance (night runs); 'off': nothing."""

    PIPER = "~/.local/share/piper/de_DE-thorsten-high.onnx"

    def __init__(self, mode: str = "play", voice: str = "thorsten", folder: str | None = None):
        import os
        # 'thorsten': local neural voice (Piper) - the macOS voices sounded terrible (Samuel, 24.10.)
        if voice == "thorsten" and not os.path.exists(os.path.expanduser(self.PIPER)):
            voice = "Anna"
        self.mode, self.voice = mode, voice
        self.folder = folder or os.path.expanduser("~/.cache/inkpartner/speech")
        self.log: list[tuple[str, str]] = []

    def muted(self) -> bool:
        import subprocess
        try:
            out = subprocess.run(["osascript", "-e", "output muted of (get volume settings)"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            return out == "true"
        except Exception:
            return True                           # cannot tell: stay silent

    def __call__(self, text: str):
        import os
        import subprocess
        import time
        sentences = [x for x in re.split(r"(?<=[.!?])\s+", text.strip()) if x]
        if self.mode == "off" or not sentences or not all(speakable(x) for x in sentences):
            self.log.append(("refused", text))
            return
        os.makedirs(self.folder, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if self.voice == "thorsten":
            import shlex
            wav = os.path.join(self.folder, stamp + ".wav")
            make = (f"printf %s {shlex.quote(text)} | ~/.local/bin/piper -m {self.PIPER} -f {shlex.quote(wav)}"
                    " >/dev/null 2>&1")
            play = f" && afplay {shlex.quote(wav)}"
        else:
            wav = os.path.join(self.folder, stamp + ".aiff")
            make = f"say -v {self.voice} -o {shlex_quote(wav)} {shlex_quote(text)}"
            play = f" && afplay {shlex_quote(wav)}"
        if self.mode == "file":
            subprocess.Popen(["sh", "-c", make])
            self.log.append(("file", wav))
        elif self.muted():
            self.log.append(("muted", text))
        else:
            subprocess.Popen(["sh", "-c", make + play])
            self.log.append(("spoken", text))
