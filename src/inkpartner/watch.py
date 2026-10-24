"""The watcher: finds where the student is writing, reviews when the pen rests, writes back without
ever throwing them out of the notebook.

Where is the student writing? Nobody tells the agent. Every few seconds it lists the modification
time and size of every page file on the tablet (one SSH call). The page that changed last is the
page being written on - in any notebook, also a new one. Measured 2026-10-23: a notebook opened a
minute earlier ("inkpartnertest") was the newest file at once. The tablet saves while writing, not
only on close (save probe, 2026-10-20). `lastOpened` in the metadata is NOT used: it lags until the
notebook is closed.

The agent's own writes change the file too. Every page the agent wrote is remembered with the hash
it left behind; a change that only shows that hash is the agent's echo, not the student.

How to write back:
- pen  (V-Pen, algebra-agent/inject.py): pen events into the open page. No restart, never throws the
  student out. Price: the ink takes the colour of the pen currently selected and lands in the
  student's layer. The viewport comes from the page thumbnail, a probe stroke checks it (penpath.py).
- file (append an agent layer + restart the notes app): colour and own layer, but a restart - and a
  restart LOGS THE STUDENT OUT (seen 2026-10-23: back to the passcode screen). Last resort only:
  off unless --allow-restart, then only after `restart_quiet_s` (default 30 min) without any change
  on ANY page, at most once per `restart_gap_s` (default 1 h). A quiet page is not an idle student -
  on 2026-10-23 the student sat reading the page for 4 minutes and was thrown out.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import page as pagemod
from . import review, verify

XOCHITL = "/home/root/.local/share/remarkable/xochitl"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Tablet:
    """Everything that touches the tablet, over SSH. Reads are free; writes are two: pen events into
    /dev/input/<pen> (pen path) and one page file + restart (file path)."""

    def __init__(self, host: str = "remarkable", guard=None, monitor=None, allow_restart=False,
                 device: str = "event2"):
        from .guards import Guard
        self.host = host
        self.guard = guard or Guard(Path.home() / ".cache/inkpartner/STOP")
        self.monitor = monitor
        self.allow_restart = allow_restart
        self.device = device

    def ssh(self, cmd: str, data: bytes | None = None, timeout: float = 30) -> bytes:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", self.host, cmd],
                           input=data, capture_output=True, timeout=timeout)
        if r.returncode != 0 and not (data and b"Invalid argument" in r.stderr):
            raise RuntimeError(r.stderr.decode(errors="replace").strip() or f"ssh exit {r.returncode}")
        return r.stdout

    def scan(self) -> dict[str, tuple[int, int]]:
        """page path (doc/page.rm) -> (mtime, size) for every page on the tablet. The tablet's own
        clock comes along ('now'), so ages are measured on one clock, not across two devices."""
        out = self.ssh(f"date +%s; cd {XOCHITL} && stat -c '%Y %s %n' */*.rm 2>/dev/null; true")
        lines = out.decode().splitlines()
        self.clock = int(lines[0]) if lines and lines[0].isdigit() else int(time.time())
        pages = {}
        for line in lines[1:]:
            parts = line.split(" ", 2)
            if len(parts) == 3:
                pages[parts[2]] = (int(parts[0]), int(parts[1]))
        return pages

    def fetch(self, rel: str) -> bytes:
        return self.ssh(f"cat {shlex.quote(XOCHITL + '/' + rel)}")

    def thumbnail(self, rel: str) -> bytes | None:
        """The notes app's picture of the page as displayed (written ~20 s after a save)."""
        doc, page = rel.split("/")[0], rel.split("/")[1].removesuffix(".rm")
        try:
            png = self.ssh(f"cat {shlex.quote(f'{XOCHITL}/{doc}.thumbnails/{page}.png')}")
        except RuntimeError:
            return None
        return png or None

    def background(self, rel: str):
        """The printed PDF page under this page, or None (notebook page, template only)."""
        from . import background as bgmod
        doc, page = rel.split("/")[0], rel.split("/")[1].removesuffix(".rm")
        try:
            info = bgmod.page_info(self.ssh(f"cat {XOCHITL}/{doc}.content"), page)
        except Exception:
            return None
        if info["pdf_page"] is None:
            return None
        cache = getattr(self, "_pdf_cache", {})
        self._pdf_cache = cache
        if doc not in cache:
            cache[doc] = self.ssh(f"cat {XOCHITL}/{doc}.pdf", timeout=120)
        return bgmod.render_pdf_page(cache[doc], info["pdf_page"])

    def strokes(self, data: bytes) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "page.rm")
            Path(p).write_bytes(data)
            return pagemod.read_strokes(p)

    def send(self, screen_strokes: list[dict]):
        """Pen events, screen pixels. `cat` reports EINVAL on this device even when every event
        arrives (algebra-agent, 20.10.): the exit code says nothing - only reading back does."""
        from . import penstream
        mon = self.monitor
        if mon:
            mon.injecting = True
        try:
            self.ssh(f"cat > /dev/input/{shlex.quote(self.device)}", data=penstream.build(screen_strokes), timeout=60)
        finally:
            if mon:
                mon.injecting = False

    def name(self, rel: str) -> str:
        doc = rel.split("/")[0]
        try:
            return json.loads(self.ssh(f"cat {XOCHITL}/{doc}.metadata"))["visibleName"]
        except Exception:
            return doc

    def open_page(self) -> tuple[str, str] | None:
        """(document, page) open on the screen, from the notes app's own log. None if unknown/closed."""
        out = self.ssh("journalctl -u xochitl --since '-12 h' --no-pager -o cat | "
                       "grep -E 'EntityOpen::open|loaded pageId=|now exiting' | tail -n 40").decode()
        doc = page = None
        for line in out.splitlines():
            if "EntityOpen::open" in line and "{" in line:
                doc, page = line.split("{", 1)[1].split("}", 1)[0], None
            elif "loaded pageId=" in line and doc:
                page = line.split("loaded pageId=", 1)[1].split()[0].rstrip(",")
            elif "now exiting" in line and doc and doc in line:
                doc = page = None
        return (doc, page) if doc and page else None

    def write_file_and_restart(self, rel: str, data: bytes, expected_sha: str, *, quiet_s: float):
        """File path - guarded: restart allowed, long quiet, real pen idle, bytes only appended."""
        original = self.fetch(rel)
        if sha(original) != expected_sha:
            raise RuntimeError("page changed since review - not restarting")
        self.guard.check_prefix(original, data)
        self.guard.before_restart(allowed=self.allow_restart, quiet_s=quiet_s,
                                  pen_idle_s=self.monitor.idle_s() if self.monitor else None)
        target = shlex.quote(XOCHITL + "/" + rel)
        self.ssh(f"systemctl stop xochitl && cat > {target}.inkpartner && mv {target}.inkpartner {target}"
                 f" ; systemctl start xochitl", data=data, timeout=60)


class PenChannel:
    """Pen events into the open page (idea and device facts from algebra-agent's V-Pen; the event
    stream is penstream.py, the placement and probe penpath.py). Guarded before every delivery."""

    def __init__(self, tablet):
        from .penpath import PenPath
        self.tablet = tablet
        self.path = PenPath(tablet)

    @property
    def landed(self):
        return self.path.landed

    def deliver(self, strokes: list[dict], rel: str) -> dict:
        doc, page = rel.split("/")[0], rel.split("/")[1].removesuffix(".rm")
        mon = self.tablet.monitor
        self.tablet.guard.before_pen(target_doc=doc, target_page=page, open_page=self.tablet.open_page(),
                                     pen_idle_s=mon.idle_s() if mon else None, viewport_ok=True)
        return self.path.deliver(strokes, rel)


class PenMonitor:
    """Reads the pen device (read-only) to know when the real pen is in use. Events that arrive while
    the agent itself injects are not counted as the student's."""

    def __init__(self, host: str, device: str = "event2"):
        import threading
        self.host, self.device = host, device
        self.last_real: float | None = None
        self.started = time.time()
        self.injecting = False
        self.activity: list[float] = []
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        import struct
        p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", self.host, f"cat /dev/input/{self.device}"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        while True:
            chunk = p.stdout.read(24 * 32)
            if not chunk:
                return
            if not self.injecting:
                now = time.time()
                self.last_real = now
                self.activity = [t for t in self.activity if now - t < 3600] + [now]

    def idle_s(self) -> float | None:
        """Seconds since the real pen last did anything; None until the monitor has watched a while."""
        if self.last_real is None:
            watched = time.time() - self.started
            return watched if watched >= 5 else None
        return time.time() - self.last_real

    def active_between(self, t0: float, t1: float) -> bool:
        return any(t0 <= t <= t1 for t in self.activity)


@dataclass
class PageState:
    stamp: tuple[int, int]
    last_change: float
    reviewed_sha: str = ""
    own_sha: str = ""                                   # what the agent itself left on the page
    delivered: set[str] = field(default_factory=set)
    pending: dict | None = None                         # feedback that could not be written yet
    own_sigs: set[str] = field(default_factory=set)     # pen-path strokes: agent ink in the student's layer
    help_levels: dict = field(default_factory=dict)     # task -> how often help was given (tutor.py)
    verdicts: dict = field(default_factory=dict)        # action key -> [bbox, verdict] of green/red marks


class Watcher:
    def __init__(self, tablet: Tablet, model, *, subject=None, settle_s=4.0, restart_quiet_s=1800.0,
                 allow_restart=False, recent_s=600.0, pen=True, log=print, state_file=None,
                 speak=None, speech_allowed=False, pen_rest_s=900.0, restart_gap_s=3600.0,
                 reader=None, judge_model=None, teach=True):
        self.tablet, self.model, self.subject = tablet, model, subject
        self.settle_s, self.restart_quiet_s, self.allow_restart = settle_s, restart_quiet_s, allow_restart
        self.recent_s = recent_s
        self.log = log
        self.pages: dict[str, PageState] = {}
        self.pen = None
        if pen is True:
            try:
                self.pen = PenChannel(tablet)
            except Exception as e:
                self.log(f"pen path unavailable ({e}); only the file path when the page is quiet")
        elif pen:
            self.pen = pen
        self.verify_tries, self.verify_wait_s = 5, 2.0
        self.speak, self.speech_allowed = speak, speech_allowed
        self.reader, self.judge_model = reader, judge_model
        self.teach = teach
        self.pen_failures, self.pen_rest_until, self.pen_rest_s = 0, 0.0, pen_rest_s
        self.restart_gap_s, self.last_restart = restart_gap_s, -1e18
        self.state_file = Path(state_file or Path.home() / ".cache/inkpartner/state.json")
        self._load()

    # ------------------------------------------------------------------ state
    def _load(self):
        try:
            data = json.loads(self.state_file.read_text())
            for rel, d in data.items():
                self.pages[rel] = PageState(tuple(d["stamp"]), 0.0, d["reviewed_sha"], d["own_sha"],
                                            set(d["delivered"]), own_sigs=set(d.get("own_sigs", [])),
                                            help_levels=dict(d.get("help_levels", {})),
                                            verdicts=dict(d.get("verdicts", {})))
        except (OSError, ValueError, KeyError):
            pass

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({rel: {"stamp": p.stamp, "reviewed_sha": p.reviewed_sha,
                                                     "own_sha": p.own_sha, "delivered": sorted(p.delivered),
                                                     "own_sigs": sorted(p.own_sigs),
                                                     "help_levels": p.help_levels, "verdicts": p.verdicts}
                                               for rel, p in self.pages.items()}))

    # ------------------------------------------------------------------- loop
    def tick(self):
        stamps = self.tablet.scan()
        now = self.tablet.clock                         # tablet time: mtimes are tablet time too
        first = not any(p.last_change for p in self.pages.values()) and not getattr(self, "_started", False)
        self._started = True
        for rel, stamp in stamps.items():
            st = self.pages.get(rel)
            if st is None or (first and st.last_change == 0.0):
                # at start, a page written in the last few minutes is still "current"; older is old news
                recent = now - stamp[0] <= self.recent_s
                if st is None:
                    st = self.pages[rel] = PageState(stamp, 0.0)
                st.stamp = stamp
                st.last_change = float(stamp[0]) if (recent or not first) else 0.0
                if not first:
                    self.log(f"new page: {self.tablet.name(rel)} ({rel})")
            elif st.stamp != stamp:
                st.stamp, st.last_change = stamp, now
        # escalation: feedback that could not be written waits here until a safe path is open
        for rel, st in self.pages.items():
            if st.pending:
                self.retry_pending(rel, st, now)
        # the page that changed last and has rested for settle_s is reviewed
        active = max(self.pages.items(), key=lambda kv: kv[1].last_change, default=(None, None))
        rel, st = active
        if rel is None or st.last_change == 0.0 or now - st.last_change < self.settle_s:
            return None
        data = self.tablet.fetch(rel)
        h = sha(data)
        if h in (st.reviewed_sha, st.own_sha):
            return None                                 # nothing new, or only the agent's own echo
        return self.review(rel, st, data, h, now)

    def review(self, rel: str, st: PageState, data: bytes, h: str, now: float):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "page.rm")
            Path(src).write_bytes(data)
            strokes = pagemod.read_strokes(src)
            if st.own_sigs:                             # the pen path's marks are not the student's writing
                from .penpath import stroke_sig
                strokes = [dict(x, author="agent") if stroke_sig(x) in st.own_sigs else x for x in strokes]
            t0 = time.time()
            bg = getattr(self.tablet, "background", None)
            r = review.run(strokes, model=self.model, subject=self.subject, delivered=st.delivered,
                           background=bg(rel) if bg else None,
                           reader=self.reader, judge_model=self.judge_model,
                           tutor_model=self.judge_model or self.model if self.teach else None,
                           help_levels=st.help_levels,
                           placed=[v for k, v in st.verdicts.items() if k in st.delivered])
            self.last_round = r
            by_id = {e.id: e for e in r.elements}
            for a in r.accepted:
                if a.verdict in ("correct", "wrong") and a.element in by_id:
                    st.verdicts[a.key(by_id[a.element])] = [list(by_id[a.element].bbox), a.verdict]
            self.log(f"{self.tablet.name(rel)}: {r.subject}, {len(r.elements)} elements, "
                     f"{len(r.accepted)} marks in {time.time() - t0:.1f}s via {getattr(self.model, 'used', '?')}")
            for a in r.accepted:
                self.log(f"  {a.verdict:10} {a.mark:9} {a.element} {a.text!r}")
            for a, why in r.rejected:
                self.log(f"  rejected   {a.mark:9} {a.element}: {why}")
            st.reviewed_sha = h
            if not r.strokes:
                self._save()
                return r
            if self.tablet.fetch(rel) != data:
                self.log("  student wrote meanwhile - feedback dropped, next round")
                st.reviewed_sha = ""
                return r
            # spoken help does not wait for the ink: hearing it while the pen rests is the point
            if self.speak and self.speech_allowed:
                for k, words in r.speech.items():
                    if k in r.tutor and words:
                        self.speak(words)
                        self.log(f"  spoken (level {r.tutor[k]['level']}): {words[:80]}...")
            result = self.deliver(rel, st, src, data, h, r, now)
            self.log(f"  delivery: {result}")
            self._save()
            return r

    def deliver(self, rel, st, src, data, h, r, now) -> dict:
        """Escalation (Codex session 2026-10-23): pen -> verify -> on failure rest the pen path and keep
        the feedback pending -> file path once the page is quiet (never while writing) -> speech if
        allowed -> otherwise wait and retry later. Never counted as done unless read back."""
        result = {}
        missing = list(r.strokes)
        from .guards import GuardError, Stopped
        if self.pen is not None and now >= self.pen_rest_until:
            t_send = time.time()
            try:
                sent = self.pen.deliver(r.strokes, rel)
            except Stopped:
                raise
            except GuardError as e:
                self.log(f"  pen refused: {e}")
                sent = None
            finally:
                from .penpath import stroke_sig
                st.own_sigs |= {stroke_sig(x) for x in getattr(self.pen, "landed", [])}
            if sent is None:
                st.pending = {"strokes": list(r.strokes), "base_sha": h, "speech": "", "since": now}
                self.retry_pending(rel, st, now)
                return {"path": "pen", "refused": True, "pending": True}
            before = pagemod.read_strokes(src)
            states, after_bytes = {}, data
            for _ in range(self.verify_tries):              # xochitl saves the pen strokes itself, a bit later
                time.sleep(self.verify_wait_s)
                after_bytes = self.tablet.fetch(rel)
                with tempfile.TemporaryDirectory() as tmp:
                    a = os.path.join(tmp, "after.rm")
                    Path(a).write_bytes(after_bytes)
                    after = pagemod.read_strokes(a)
                states = verify.verify(r.strokes, before, after)
                if all(v == "confirmed" for v in states.values()):
                    break
            mon = self.tablet.monitor
            self.tablet.guard.after_pen(before=before, after=after, expected=r.strokes,
                                        real_pen_during=bool(mon and mon.active_between(t_send, time.time())))
            st.own_sha = sha(after_bytes)
            st.delivered |= {k for k, v in states.items() if v == "confirmed"}
            result = {"path": "pen", "sent": sent.get("status"), "verified": states}
            if all(v == "confirmed" for v in states.values()):
                self.pen_failures = 0
                return result
            # only what is surely missing may be written again; 'unclear' may already be on the page
            missing = [s for s in r.strokes if states.get(s["action"]) == "missing"]
            if all(v == "missing" for v in states.values()):
                self.pen_failures += 1
                if self.pen_failures >= 2:
                    self.pen_rest_until = now + self.pen_rest_s
                    self.log(f"  pen path failed {self.pen_failures}x in a row - resting it for "
                             f"{self.pen_rest_s / 60:.0f} min")
        if missing:
            speech = " ".join(v for k, v in r.speech.items() if any(s["action"] == k for s in missing))
            st.pending = {"strokes": missing, "base_sha": sha(self.tablet.fetch(rel)), "speech": speech,
                          "since": now}
            result["pending"] = len({s["action"] for s in missing})
            self.retry_pending(rel, st, now)
        return result

    def _is_open(self, rel) -> bool:
        op = getattr(self.tablet, "open_page", None)
        try:
            return bool(op) and op() == (rel.split("/")[0], rel.split("/")[1].removesuffix(".rm"))
        except Exception:
            return False

    def _pen_retry(self, rel, st, p, current) -> bool:
        """Pending feedback through the pen, read back like a first delivery. True if anything landed."""
        from .guards import GuardError, Stopped
        from .penpath import stroke_sig
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "before.rm")
            Path(a).write_bytes(current)
            before = pagemod.read_strokes(a)
        try:
            self.pen.deliver(p["strokes"], rel)
        except Stopped:
            raise
        except GuardError as e:
            self.log(f"  pending, pen refused: {e}")
            return False
        finally:
            st.own_sigs |= {stroke_sig(x) for x in getattr(self.pen, "landed", [])}
        after_bytes, states = current, {}
        for _ in range(self.verify_tries):
            time.sleep(self.verify_wait_s)
            after_bytes = self.tablet.fetch(rel)
            with tempfile.TemporaryDirectory() as tmp:
                a = os.path.join(tmp, "after.rm")
                Path(a).write_bytes(after_bytes)
                after = pagemod.read_strokes(a)
            states = verify.verify(p["strokes"], before, after)
            if all(v == "confirmed" for v in states.values()):
                break
        st.own_sha = sha(after_bytes)
        st.delivered |= {k for k, v in states.items() if v == "confirmed"}
        missing = [s for s in p["strokes"] if states.get(s["action"]) == "missing"]
        st.pending = ({**p, "strokes": missing, "base_sha": st.own_sha} if missing else None)
        self.log(f"  {self.tablet.name(rel)}: pending feedback delivered on return: {states}")
        self._save()
        return any(v == "confirmed" for v in states.values())

    def retry_pending(self, rel, st, now):
        p = st.pending
        current = self.tablet.fetch(rel)
        if sha(current) != p["base_sha"]:
            self.log(f"  {self.tablet.name(rel)}: page changed since - pending feedback dropped (stale)")
            st.pending = None
            st.reviewed_sha = ""                          # look at the page again
            return
        # back on the page: the pen path can deliver now (round 7: feedback for a page the student
        # left before the pen pause was lost when they came back without writing)
        if self.pen is not None and now >= self.pen_rest_until and self._is_open(rel):
            if self._pen_retry(rel, st, p, current):
                return
        # idle = no change on ANY page; a page the student only reads is quiet but not idle
        quiet = now - max(x.last_change for x in self.pages.values())
        if (self.allow_restart and quiet >= self.restart_quiet_s
                and now - self.last_restart >= self.restart_gap_s):
            from .guards import GuardError, Stopped
            self.last_restart = now
            with tempfile.TemporaryDirectory() as tmp:
                src, out = os.path.join(tmp, "in.rm"), os.path.join(tmp, "out.rm")
                Path(src).write_bytes(current)
                pagemod.append_strokes(src, p["strokes"], out)
                new = Path(out).read_bytes()
            try:
                self.tablet.write_file_and_restart(rel, new, p["base_sha"], quiet_s=quiet)
            except Stopped:
                raise
            except GuardError as e:
                self.log(f"  restart refused: {e}")
                return
            back = self.tablet.fetch(rel)
            st.own_sha = sha(back)
            if back == new:
                st.delivered |= {s["action"] for s in p["strokes"]}
                st.pending = None
                self.log(f"  {self.tablet.name(rel)}: written via file path (page quiet {quiet:.0f}s), verified")
            else:
                self.log(f"  {self.tablet.name(rel)}: file path did not verify - stays pending")
            self._save()
            return
        if p.get("speech") and self.speak and self.speech_allowed and not p.get("spoken"):
            self.speak(p["speech"])
            p["spoken"] = True
            self.log("  spoken while writing is not possible")


def run(host="remarkable", model=None, subject=None, interval_s=3.0, once=False, **kw):
    """Loop forever (or until the first review with --once). Stops for good on the kill switch."""
    from . import models
    from .guards import Stopped
    tablet = Tablet(host, monitor=PenMonitor(host),
                    allow_restart=kw.get("allow_restart", False))
    w = Watcher(tablet, models.get(model), subject=subject, **kw)
    w.log(f"watching {host} every {interval_s}s with {w.model.name}; pen path: {'yes' if w.pen else 'no'}")
    while True:
        try:
            r = w.tick()
            if once and r is not None:
                return r
        except (KeyboardInterrupt, Stopped):
            raise
        except Exception as e:
            w.log(f"error: {e}")
        time.sleep(interval_s)


def pentest(host="remarkable", wait_s=2.0) -> dict:
    """One guarded pen delivery: a small check in free space next to the last line of the open page.
    Every guard applies (open page, pen away, kill switch, rate); the probe goes first; the page is
    read back. For the supervised device tests before the watcher may run alone."""
    from . import layout, marks
    tablet = Tablet(host, monitor=PenMonitor(host))
    time.sleep(6)                                       # the monitor must watch a while: pen away?
    op = tablet.open_page()
    if op is None:
        return {"status": "no open page"}
    rel = f"{op[0]}/{op[1]}.rm"
    before = tablet.strokes(tablet.fetch(rel))
    user = [s for s in before if s.get("author") == "user"]
    if not user:
        return {"status": "page has no writing to place the check next to"}
    last = max(user, key=lambda s: max(p[1] for p in s["points"]))
    line = [s for s in user if abs(max(p[1] for p in s["points"]) - max(p[1] for p in last["points"])) < 80]
    spot = layout.place((70, 70), marks.bbox_of(line), layout.Occupancy(before, pagemod.PAGE_W, pagemod.PAGE_H))
    plan = [{**s, "action": "check"} for s in marks.check(spot["rect"])]
    pen = PenChannel(tablet)
    pen.path.wait_s = wait_s
    from .guards import GuardError
    try:
        sent = pen.deliver(plan, rel)
    except GuardError as e:
        return {"status": "refused", "why": str(e), **pen.path.last, "landed": len(pen.landed)}
    time.sleep(wait_s)
    after = tablet.strokes(tablet.fetch(rel))
    tablet.guard.after_pen(before=before, after=after, expected=plan,
                           real_pen_during=False)
    return {"status": "verified" if all(v == "confirmed" for v in verify.verify(plan, before, after).values())
            else "not verified", "page": rel, "target": [round(v) for v in spot["rect"]], **sent}
