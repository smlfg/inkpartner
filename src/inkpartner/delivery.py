"""Getting feedback to the student without ever interrupting them, and without asking them to debug.

Rules (Samuel, Codex session 2026-10-23):
- Writing must never stop or restart the notes app. A channel that would is not a channel here.
- Delivery is only done when the ink is verified on the page.
- On failure the agent retries by itself, a bounded number of times with growing pauses, then rests
  the broken channel (circuit breaker) instead of hammering it.
- Speech is off unless the student allowed it for this session; muted stays muted.
- Before a late delivery, the agent checks that the feedback still fits the page: if the student has
  changed or erased the element meanwhile, the feedback is dropped, not delivered.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time


@dataclass
class Pending:
    key: str                    # action key (element fingerprint : verdict : mark)
    strokes: list[dict]
    speech: str = ""            # natural language only; empty = nothing to say
    attempts: int = 0
    status: str = "queued"      # queued | confirmed | unclear | dropped | resting
    next_try: float = 0.0
    log: list[str] = field(default_factory=list)


class Breaker:
    """After `limit` failures in a row a channel rests for `rest_s`, then gets one trial."""

    def __init__(self, limit: int = 3, rest_s: float = 60.0):
        self.limit, self.rest_s = limit, rest_s
        self.failures, self.open_until = 0, 0.0

    def allowed(self, now: float) -> bool:
        return now >= self.open_until

    def record(self, ok: bool, now: float):
        if ok:
            self.failures = 0
            return
        self.failures += 1
        if self.failures >= self.limit:
            self.open_until = now + self.rest_s
            self.failures = 0


class Outbox:
    """Holds feedback until it is verified on the page. `channel.deliver(strokes)` writes ink;
    `read_page()` returns the current strokes; `still_valid(key)` says whether the element is unchanged."""

    def __init__(self, channel, read_page, still_valid, *, speak=None, speech_allowed: bool = False,
                 backoff=(2.0, 5.0, 15.0), max_attempts: int = 3, clock=time.monotonic):
        self.channel, self.read_page, self.still_valid = channel, read_page, still_valid
        self.speak, self.speech_allowed = speak, speech_allowed
        self.backoff, self.max_attempts, self.clock = backoff, max_attempts, clock
        self.breaker = Breaker()
        self.items: dict[str, Pending] = {}
        self.delivered: set[str] = set()

    def add(self, item: Pending):
        if item.key not in self.delivered and item.key not in self.items:
            self.items[item.key] = item

    def tick(self):
        """One pass over the queue. Call it from the agent's timer; it never blocks the student."""
        from .verify import verify
        now = self.clock()
        for item in list(self.items.values()):
            if item.status in ("confirmed", "dropped") or now < item.next_try:
                continue
            if not self.still_valid(item.key):
                self._close(item, "dropped", "element changed since - feedback no longer fits")
                continue
            before = self.read_page()
            if item.status == "unclear":
                # it may have landed late: look again before writing again
                state = verify(item.strokes, [], before).get(item.key)
                if state == "confirmed":
                    self._close(item, "confirmed", "arrived late")
                    continue
            if not self.breaker.allowed(now):
                item.status = "resting"
                self._fallback(item)
                continue
            item.attempts += 1
            try:
                self.channel.deliver(item.strokes)
                state = verify(item.strokes, before, self.read_page()).get(item.key, "missing")
            except Exception as exc:          # a channel error is not proof that nothing arrived
                item.log.append(f"channel error: {exc}")
                state = verify(item.strokes, before, self.read_page()).get(item.key, "unclear")
            self.breaker.record(state == "confirmed", now)
            if state == "confirmed":
                self._close(item, "confirmed", f"verified after {item.attempts} attempt(s)")
            elif item.attempts >= self.max_attempts:
                item.status = "resting"
                item.next_try = now + self.breaker.rest_s
                item.attempts = 0
                self._fallback(item)
            else:
                item.status = state if state == "unclear" else "queued"
                item.next_try = now + self.backoff[min(item.attempts - 1, len(self.backoff) - 1)]

    def _fallback(self, item: Pending):
        if self.speak and self.speech_allowed and item.speech and "spoken" not in item.log:
            self.speak(item.speech)
            item.log.append("spoken")

    def _close(self, item: Pending, status: str, why: str):
        item.status = status
        item.log.append(why)
        if status == "confirmed":
            self.delivered.add(item.key)
        self.items.pop(item.key, None)
