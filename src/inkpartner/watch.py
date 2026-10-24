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


def focus(strokes: list[dict], newest: int = 8, above: float = 900.0, below: float = 150.0) -> list[dict]:
    """Only the part of the page around the newest writing goes to the model. A long page (7600 px on
    2026-10-24) took 30-50 s per round; old lines already have their feedback. The window keeps the
    exercise above the new lines for context."""
    user = [s for s in strokes if s.get("author") == "user" and s["points"]]
    if len(user) <= newest:
        return strokes
    ys = [p[1] for s in user[-newest:] for p in s["points"]]
    lo, hi = min(ys) - above, max(ys) + below
    return [s for s in strokes if s["points"] and lo <= min(p[1] for p in s["points"]) and
            max(p[1] for p in s["points"]) <= hi]


def parse_open_page(log: str) -> tuple[str, str] | None:
    """The last document opened, its last loaded page, and the page last saved while it is open."""
    doc = page = None
    for line in log.splitlines():
        if "EntityOpen::open" in line and "{" in line:
            doc, page = line.split("{", 1)[1].split("}", 1)[0], None
        elif "loaded pageId=" in line and doc and "no file found" not in line:
            page = line.split("loaded pageId=", 1)[1].split()[0].rstrip(",")
        elif "Scene written to" in line and "/xochitl/" in line:
            d, _, f = line.split("/xochitl/", 1)[1].split('"')[0].partition("/")
            if d == doc or doc is None:
                doc, page = d, f.split(".rm")[0]
        elif "now exiting" in line and doc and doc in line:
            doc = page = None
    return (doc, page) if doc and page else None


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
        self.pace_s = 0.002                             # between pen reports when writing

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

    def pen_viewport(self, page_strokes: list[dict]):
        """Viewport from the student's own last strokes: screen (pen events) against page (file)."""
        from . import viewport
        mon = self.monitor
        if not mon or not mon.reader.strokes:
            return None
        user = [s for s in page_strokes if s.get("author") == "user" and not s.get("live")]
        return viewport.from_pen([pts for _, pts in mon.reader.strokes], user, max_shift=40)

    def known_viewport(self, rel: str, page_strokes: list[dict]):
        """(viewport, source): measured from the pen now, or remembered for this page as long as no
        finger touched the screen since (scrolling and zooming are finger gestures). (None, None) if
        neither - then the caller falls back to the thumbnail and the probe stroke."""
        cache = self.__dict__.setdefault("_vp_cache", {})
        vp = self.pen_viewport(page_strokes)
        if vp is not None:
            cache[rel] = (vp, time.time())
            return vp, "pen"
        mon = self.monitor
        if rel in cache and mon is not None and mon.last_touch < cache[rel][1]:
            return cache[rel][0], "remembered"
        from . import calibrate                         # measured with the agent's own L
        c = calibrate.load(rel)
        if c and mon is not None and mon.last_touch < c[1]:
            return c[0], "remembered"
        return None, None

    def live_strokes(self, rel: str, page_strokes: list[dict]) -> list[dict]:
        """The student's newest strokes that the notes app has not saved yet, in page pixels, from
        the pen. Live test 24.10.: the app saved up to a minute late, the agent waited for the file."""
        vp = self.pen_viewport(page_strokes)
        if vp is None or not getattr(vp, "shift", 0):
            return []
        self.__dict__.setdefault("_vp_cache", {})[rel] = (vp, time.time())
        out = []
        for _, pts in self.monitor.reader.strokes[-vp.shift:]:
            out.append({"points": [[*vp.to_page(x, y), 0.6] for x, y in pts], "color": "black",
                        "author": "user", "live": True})
        return out

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
            # at the pen's pace, one report every ~2 ms (a block at once: 'Timeout while waiting for
            # penpoint', nothing drawn - live test 24.10.)
            p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", self.host,
                                  f"cat > /dev/input/{shlex.quote(self.device)}"],
                                 stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            for rep in penstream.reports(penstream.build(screen_strokes)):
                p.stdin.write(rep)
                p.stdin.flush()
                time.sleep(self.pace_s)
            p.stdin.close()
            p.wait(timeout=30)
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
        """(document, page) open on the screen, from the notes app's own log. None if unknown/closed.
        Since boot, not the last 12 h: on 2026-10-24 a notebook opened the evening before was still
        open the next afternoon, and a 12 h window saw nothing."""
        out = self.ssh("journalctl -u xochitl -b --no-pager -o cat | "
                       "grep -E 'EntityOpen::open|loaded pageId=|now exiting|Scene written to' | tail -n 60").decode()
        return parse_open_page(out)

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
        from .penstream import Reader
        self.host, self.device = host, device
        self.reader = Reader()                          # the student's strokes in screen pixels
        self.last_touch = 0.0                           # last finger on the screen: scroll or zoom
        self.last_real: float | None = None
        self.started = time.time()
        self.injecting = False
        self.activity: list[float] = []
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        threading.Thread(target=self._touch, daemon=True).start()

    def _touch(self, device: str = "event3"):
        """Fingers scroll and zoom. Any touch makes a remembered viewport doubtful."""
        p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", self.host, f"cat /dev/input/{device}"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        while p.stdout.read(24 * 8):
            self.last_touch = time.time()

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
                self.reader.feed(chunk)

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
    expected: list = field(default_factory=list)        # marks sent without read-back: agent ink once saved


class Watcher:
    def __init__(self, tablet: Tablet, model, *, subject=None, settle_s=3.0, restart_quiet_s=1800.0,
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
        self.verify_tries, self.verify_wait_s = 8, 1.0
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
                                            verdicts=dict(d.get("verdicts", {})),
                                            expected=list(d.get("expected", [])))
        except (OSError, ValueError, KeyError):
            pass

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({rel: {"stamp": p.stamp, "reviewed_sha": p.reviewed_sha,
                                                     "own_sha": p.own_sha, "delivered": sorted(p.delivered),
                                                     "own_sigs": sorted(p.own_sigs),
                                                     "help_levels": p.help_levels, "verdicts": p.verdicts,
                                                     "expected": p.expected[-100:]}
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
        if first:
            # retroactive: the page open at start is looked at once, however old its writing
            op = self.tablet.open_page() if hasattr(self.tablet, "open_page") else None
            rel0 = f"{op[0]}/{op[1]}.rm" if op else None
            if rel0 in self.pages and self.pages[rel0].last_change == 0.0:
                self.pages[rel0].last_change = float(self.pages[rel0].stamp[0])
        # the pen says the student wrote and paused; the file may come up to a minute later
        live = self._pen_review(now)
        if live is not None:
            return live
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

    def _pen_review(self, now):
        mon = getattr(self.tablet, "monitor", None)
        if mon is None or not hasattr(mon, "reader") or not hasattr(self.tablet, "live_strokes"):
            return None
        n = len(mon.reader.strokes)
        if n == getattr(self, "_pen_reviewed", 0) or (mon.idle_s() or 0) < self.settle_s:
            return None
        self._pen_reviewed = n
        op = self.tablet.open_page()
        if not op:
            return None
        rel = f"{op[0]}/{op[1]}.rm"
        data = self.tablet.fetch(rel)
        live = self.tablet.live_strokes(rel, self.tablet.strokes(data))
        if not live:
            return None                                 # all saved already, or no viewport: the file path decides
        st = self.pages.setdefault(rel, PageState(self.tablet.scan().get(rel, (0, 0)), now))
        self.log(f"  pen: {len(live)} stroke(s) not saved yet - reviewing from the pen")
        return self.review(rel, st, data, sha(data) + f":pen{n}", now, extra=live)

    def review(self, rel: str, st: PageState, data: bytes, h: str, now: float, extra: list | None = None):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "page.rm")
            Path(src).write_bytes(data)
            strokes = pagemod.read_strokes(src)
            from .penpath import stroke_sig
            if st.expected:                             # marks sent without read-back, now saved
                for x in strokes:
                    if x.get("author") == "user" and stroke_sig(x) not in st.own_sigs and \
                            verify.coverage({"points": x["points"]}, st.expected, tol=10) >= 0.8:
                        st.own_sigs.add(stroke_sig(x))
            if st.own_sigs:                             # the pen path's marks are not the student's writing
                strokes = [dict(x, author="agent") if stroke_sig(x) in st.own_sigs else x for x in strokes]
            strokes = strokes + list(extra or [])       # what the pen wrote that the file has not caught up with
            strokes = focus(strokes)
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
            mon = getattr(self.tablet, "monitor", None)
            wrote = bool(mon and hasattr(mon, "active_between") and mon.active_between(t0, time.time()))
            # a review from the pen: the app saving those very strokes meanwhile is no new writing
            if (wrote if extra else self.tablet.fetch(rel) != data):
                self.log("  student wrote meanwhile - feedback dropped, next round")
                st.reviewed_sha = ""
                return r
            # spoken help does not wait for the ink: hearing it while the pen rests is the point
            if self.speak and self.speech_allowed:
                for k, words in r.speech.items():
                    if k in r.tutor and words:
                        self.speak(words)
                        self.log(f"  spoken (level {r.tutor[k]['level']}): {words[:80]}...")
            t_del = time.time()
            result = self.deliver(rel, st, src, data, h, r, now)
            self.log(f"  delivery: {result}")
            self.log(f"  timing: pause {self.settle_s:.0f}s + reading/judging {t_del - t0:.1f}s {r.timing} + "
                     f"writing {time.time() - t_del:.1f}s")
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
            if sent.get("status") == "sent_direct":
                # measured viewport, no read-back wait (the app saves late). Counted as delivered so
                # it is never sent twice; once saved, the marks are recognised as agent ink (expected).
                st.delivered |= {s["action"] for s in r.strokes}
                st.expected = (st.expected + [{"points": s["points"]} for s in r.strokes])[-300:]
                self.pen_failures = 0
                return {"path": "pen", **sent}
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
        # only when something could have changed: new pen strokes (a viewport) since the last try.
        # Live test 24.10.: retrying every tick used up the pen rate limit (R-RATE) for nothing.
        mon = getattr(self.tablet, "monitor", None)
        seen = len(mon.reader.strokes) if mon and hasattr(mon, "reader") else None
        if (self.pen is not None and now >= self.pen_rest_until and self._is_open(rel)
                and (seen is None or seen != p.get("pen_seen"))):
            p["pen_seen"] = seen
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


def run(host="remarkable", model=None, subject=None, interval_s=1.5, once=False, **kw):
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


def pentest(host="remarkable", wait_s=2.0, write_timeout=120.0, log=print) -> dict:
    """One guarded pen delivery: a small check in free space next to the line the student writes
    now. Waits for that line: its pen events (screen) and its saved strokes (page) give the viewport.
    Every guard applies; the probe goes first; the page is read back."""
    from . import layout, marks
    tablet = Tablet(host, monitor=PenMonitor(host))
    time.sleep(3)
    op = tablet.open_page()
    if op is None:
        return {"status": "no open page"}
    rel = f"{op[0]}/{op[1]}.rm"
    log(f"open page: {tablet.name(rel)}. Write a short line now (two words), then put the pen away.")
    t0 = time.time()
    while not tablet.monitor.reader.strokes and time.time() - t0 < write_timeout:
        time.sleep(1)
    if not tablet.monitor.reader.strokes:
        return {"status": "nothing written - no viewport from the pen"}
    while (tablet.monitor.idle_s() or 0) < 6:            # the line is finished, the app has saved it
        time.sleep(1)
    before = tablet.strokes(tablet.fetch(rel))
    user = [s for s in before if s.get("author") == "user"]
    n = min(len(tablet.monitor.reader.strokes), len(user))
    line = user[-n:]                                     # the strokes just written, newest in the file
    spot = layout.place((70, 70), marks.bbox_of(line), layout.Occupancy(before, pagemod.PAGE_W, pagemod.PAGE_H))
    plan = [{**s, "action": "check"} for s in marks.check(spot["rect"])]
    pen = PenChannel(tablet)
    pen.path.wait_s = wait_s
    from .guards import GuardError
    vp = tablet.pen_viewport(before)
    info = {"page": rel, "pen_strokes": len(tablet.monitor.reader.strokes), "line": [round(v) for v in marks.bbox_of(line)],
            "pen_viewport": vp and [round(vp.scale, 3), round(vp.ox), round(vp.oy), vp.score],
            "target": [round(v) for v in spot["rect"]]}
    try:
        sent = pen.deliver(plan, rel)
    except GuardError as e:
        return {"status": "refused", "why": str(e), **info, **pen.path.last, "landed": len(pen.landed)}
    time.sleep(wait_s)
    after = tablet.strokes(tablet.fetch(rel))
    tablet.guard.after_pen(before=before, after=after, expected=plan, real_pen_during=False)
    return {"status": "verified" if all(v == "confirmed" for v in verify.verify(plan, before, after).values())
            else "not verified", **info, **sent}
