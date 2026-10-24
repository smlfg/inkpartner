import json
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from inkpartner import delivery, layout, marks, mathcheck, page, plan, profiles, review, speech, verify
from inkpartner.elements import Element

HERE = os.path.dirname(__file__)
FIX = os.path.join(HERE, "fixtures", "synthetic-dod-l1.rm")


def el(eid, text, y, **kw):
    return Element(id=eid, kind=kw.pop("kind", "line"), bbox=[100, y, 400, y + 50], text=text,
                   confidence=kw.pop("confidence", 0.95), **kw)


class MathCheck(unittest.TestCase):
    def test_distributive_error_and_lines_built_on_it(self):
        els = [el("a", "3(x+2)=15", 100), el("b", "3x+2=15", 200), el("c", "3x=13", 300), el("d", "x = 13/3", 400)]
        self.assertEqual(mathcheck.check_steps(els), {"b": "wrong", "c": "wrong", "d": "wrong"})

    def test_real_page_completing_the_square_with_restart(self):
        # Samuel's page "Lernen", 2026-10-23, as read by eye
        lines = ["x^2+3x=1", "x^2+3x+(3/2)^2 = 1+(3/2)^2", "(x+3/2)^2 = 1+9/4", "= 9/9+9/4 = 18/13",
                 "x+3/2 = ±sqrt(18/13)", "1+9/4 = 4/4+9/4 = 13/4", "(x+3/2)^2 = 13/4",
                 "x+3/2 = ±sqrt(13/4)", "x = sqrt(13/4)-3/2", "x = -sqrt(13/4)-3/2", "x = 13/4-3/2"]
        els = [el(f"L{i}", t, 100 * i) for i, t in enumerate(lines, 1)]
        v = mathcheck.check_steps(els)
        self.assertEqual(v, {"L2": "correct", "L3": "correct", "L4": "wrong", "L5": "wrong", "L6": "correct",
                             "L7": "correct", "L8": "correct", "L9": "correct", "L10": "correct",
                             "L11": "wrong"})

    def test_line_ending_in_equals_is_the_expression_to_expand(self):
        els = [el("a", "(z+x)^4 =", 100), el("b", "z^4+zx^4+z^4x+x^4", 200)]
        self.assertEqual(mathcheck.check_steps(els), {"b": "wrong"})
        els = [el("a", "(a+b)^2 =>", 100), el("b", "a^2+2ab+b^2", 200)]
        self.assertEqual(mathcheck.check_steps(els), {"b": "correct"})

    def test_latex_braces_from_the_model(self):
        els = [el("a", "(z+x)^2", 100), el("b", "z^{2}+2zx+x^{2}", 200)]
        self.assertEqual(mathcheck.check_steps(els), {"b": "correct"})

    def test_exercises_are_checked_separately(self):
        els = [el("a", "2x=4", 100, group="1"), el("b", "x=2", 200, group="1"),
               el("c", "x+1=5", 300, group="2"), el("d", "x=4", 400, group="2")]
        self.assertEqual(mathcheck.check_steps(els), {"b": "correct", "d": "correct"})

    def test_correct_chain_and_unparsable_line(self):
        els = [el("a", "3(x+2)=15", 100), el("b", "3x+6=15", 200), el("c", "3x=9", 300), el("d", "also", 400)]
        self.assertEqual(mathcheck.check_steps(els), {"b": "correct", "c": "correct"})

    def test_expression_rewrite(self):
        els = [el("a", "(a+b)^2", 100), el("b", "a^2+2ab+b^2", 200), el("c", "a^2+b^2", 300)]
        self.assertEqual(mathcheck.check_steps(els), {"b": "correct", "c": "wrong"})


class Rules(unittest.TestCase):
    def setUp(self):
        self.els = [el("a", "3(x+2)=15", 100), el("b", "3x+2=15", 200, confidence=0.5),
                    el("u", "", 300, legible=False, confidence=0.1)]
        self.math = profiles.get("math")

    def test_uncertain_never_green(self):
        r = plan.validate([plan.Action("b", "correct", "check")], self.els, self.math)
        self.assertEqual(r.accepted, [])
        self.assertIn("never confirmed green", r.rejected[0][1])

    def test_illegible_only_wavy(self):
        r = plan.validate([plan.Action("u", "wrong", "circle"), plan.Action("u", "unreadable", "wavy")],
                          self.els, self.math)
        self.assertEqual([a.mark for a in r.accepted], ["wavy"])

    def test_deterministic_check_overrules_model(self):
        r = plan.validate([plan.Action("a", "wrong", "circle")], self.els, self.math, overrides={"a": "correct"})
        self.assertEqual(r.accepted, [])

    def test_colour_follows_verdict(self):
        self.assertEqual(plan.Action("a", "wrong", "underline").color, "red")
        self.assertEqual(plan.Action("a", "correct", "underline").color, "green")

    def test_limit_keeps_errors_first(self):
        acts = [plan.Action("a", "correct", "check")] + [plan.Action("a", "wrong", "note", text=f"n{i}") for i in range(5)]
        r = plan.validate(acts, self.els, self.math)
        self.assertEqual(len(r.accepted), self.math.max_actions)
        self.assertTrue(all(a.verdict == "wrong" for a in r.accepted))

    def test_no_repeat_of_delivered_feedback(self):
        a = plan.Action("a", "correct", "check")
        r = plan.validate([a], self.els, self.math, delivered={a.key(self.els[0])})
        self.assertEqual(r.accepted, [])

    def test_mark_not_in_profile(self):
        r = plan.validate([plan.Action("a", "correct", "underline")], self.els, profiles.get("diagram"))
        self.assertEqual(r.accepted, [])


class Layout(unittest.TestCase):
    def test_free_space_right_of_element(self):
        occ = layout.Occupancy([], 1620, 2160)
        spot = layout.place((200, 40), [100, 100, 400, 150], occ)
        self.assertEqual(spot["how"], "right")

    def test_full_page_still_places_a_note(self):
        ink = [{"points": [[x, y, .5] for x in range(0, 1620, 10)]} for y in range(0, 2160, 10)]
        occ = layout.Occupancy(ink, 1620, 2160)
        spot = layout.place((200, 40), [100, 100, 400, 150], occ)
        self.assertEqual(spot["how"], "overlap")


class Verify(unittest.TestCase):
    def setUp(self):
        self.expected = marks.check([100, 100, 300, 150])
        for s in self.expected:
            s["action"] = "k"

    def test_confirmed_even_in_other_colour_and_layer(self):
        arrived = [{**s, "color": "black", "author": "user"} for s in self.expected]
        self.assertEqual(verify.verify(self.expected, [], arrived), {"k": "confirmed"})

    def test_missing(self):
        self.assertEqual(verify.verify(self.expected, [], []), {"k": "missing"})

    def test_partial_is_unclear(self):
        s = self.expected[0]
        half = {"points": s["points"][:1] + [[(s["points"][0][0] + s["points"][1][0]) / 2,
                                              (s["points"][0][1] + s["points"][1][1]) / 2, .7]]}
        self.assertEqual(verify.verify(self.expected, [], [half]), {"k": "unclear"})


class FakeTablet:
    def __init__(self, behaviour):
        self.ink, self.behaviour, self.calls = [], list(behaviour), 0

    def deliver(self, strokes):
        self.calls += 1
        b = self.behaviour.pop(0) if self.behaviour else "ok"
        if b in ("ok", "ok-but-error"):
            self.ink += strokes
        if b in ("error", "ok-but-error"):
            raise IOError("pen device returned an error")

    def read(self):
        return list(self.ink)


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


class Delivery(unittest.TestCase):
    def item(self, speech_text=""):
        st = marks.check([100, 100, 300, 150])
        for s in st:
            s["action"] = "k"
        return delivery.Pending("k", st, speech=speech_text)

    def outbox(self, tablet, valid=True, **kw):
        clock = Clock()
        box = delivery.Outbox(tablet, tablet.read, lambda key: valid, clock=clock, **kw)
        return box, clock

    def test_error_code_but_ink_arrived_counts_as_delivered(self):
        tab = FakeTablet(["ok-but-error"])
        box, _ = self.outbox(tab)
        box.add(self.item())
        box.tick()
        self.assertIn("k", box.delivered)
        self.assertEqual(tab.calls, 1)

    def test_retries_with_backoff_then_succeeds(self):
        tab = FakeTablet(["fail", "fail", "ok"])
        box, clock = self.outbox(tab)
        box.add(self.item())
        for t in (0, 1, 2, 3, 10, 30):
            clock.t = t
            box.tick()
        self.assertIn("k", box.delivered)
        self.assertEqual(tab.calls, 3)

    def test_no_duplicate_after_late_arrival(self):
        tab = FakeTablet(["fail"])
        box, clock = self.outbox(tab)
        it = self.item()
        box.add(it)
        box.tick()
        it.status = "unclear"
        tab.ink += it.strokes          # it landed late
        clock.t = 100
        box.tick()
        self.assertIn("k", box.delivered)
        self.assertEqual(tab.calls, 1)

    def test_stale_feedback_is_dropped(self):
        tab = FakeTablet([])
        box, _ = self.outbox(tab, valid=False)
        box.add(self.item())
        box.tick()
        self.assertEqual(tab.calls, 0)
        self.assertNotIn("k", box.delivered)

    def test_muted_stays_muted(self):
        said = []
        tab = FakeTablet(["fail"] * 9)
        box, clock = self.outbox(tab, speak=said.append, speech_allowed=False)
        box.add(self.item("Schau noch mal hin."))
        for t in range(0, 400, 5):
            clock.t = t
            box.tick()
        self.assertEqual(said, [])

    def test_speech_fallback_when_allowed(self):
        said = []
        tab = FakeTablet(["fail"] * 9)
        box, clock = self.outbox(tab, speak=said.append, speech_allowed=True)
        box.add(self.item("Schau noch mal hin."))
        for t in range(0, 400, 5):
            clock.t = t
            box.tick()
        self.assertEqual(said, ["Schau noch mal hin."])


class Speech(unittest.TestCase):
    def test_natural_language_only(self):
        self.assertTrue(speech.speakable("Schau dir noch mal an, wie du die Klammer aufgelöst hast."))
        for bad in ("3x+2=15", "Lies src/agent.py", "f(x) ist falsch", "Rechne 3 * 4", "x^2"):
            self.assertFalse(speech.speakable(bad), bad)


class PageFile(unittest.TestCase):
    def test_append_keeps_original_bytes_and_reads_back_as_agent(self):
        tmp = tempfile.mkdtemp()
        try:
            out = os.path.join(tmp, "out.rm")
            ink = marks.underline([100, 100, 400, 150], color="red") + marks.text("Hallo", (100, 300))
            info = page.append_strokes(FIX, ink, out)
            self.assertTrue(info["layer_created"])
            self.assertTrue(open(out, "rb").read().startswith(open(FIX, "rb").read()))
            back = page.read_strokes(out)
            self.assertEqual(sum(1 for s in back if s["author"] == "agent"), len(ink))
            self.assertEqual(sum(1 for s in back if s["author"] == "user"),
                             len(page.read_strokes(FIX)))
            self.assertIn("red", {s["color"] for s in back if s["author"] == "agent"})
            # second append reuses the layer
            out2 = os.path.join(tmp, "out2.rm")
            more = marks.check([100, 500, 400, 550])
            self.assertFalse(page.append_strokes(out, more, out2)["layer_created"])
            self.assertEqual(verify.verify([{**s, "action": "k"} for s in more], page.read_strokes(out),
                                           page.read_strokes(out2)), {"k": "confirmed"})
        finally:
            shutil.rmtree(tmp)


class Render(unittest.TestCase):
    def test_frame_follows_ink_beyond_the_paper(self):
        ink = [{"points": [[-454, 100, .5], [2099, 17087, .5]], "color": "black", "author": "user"}]
        img = page.render(ink, scale=0.1)
        x0, _, x1, y1 = img.info["frame"]
        self.assertLessEqual(x0, -454)
        self.assertGreaterEqual(x1, 2099)
        self.assertGreaterEqual(y1, 17087)


class Agent(unittest.TestCase):
    """The model calls with a fake client: request shape and parsing, no network."""

    def fake(self, payloads):
        calls = []

        class Fake:
            name = "fake"

            def json(self, images, prompt, schema):
                calls.append({"images": images, "prompt": prompt, "schema": schema})
                return payloads[len(calls) - 1]
        return Fake(), calls

    def test_full_round_with_fake_model(self):
        strokes = page.read_strokes(FIX)
        read = {"subject": "math", "elements": [
            {"kind": "line", "text": "3(x+2)=15", "latex": "", "box": [.1, .05, .4, .1], "confidence": .95, "legible": True},
            {"kind": "line", "text": "3x+2=15", "latex": "", "box": [.1, .12, .4, .17], "confidence": .95, "legible": True}]}
        judged = {"actions": [
            {"element": "e1", "verdict": "wrong", "mark": "circle", "text": "", "why": "Klammer", "speech": ""},
            {"element": "e1", "verdict": "wrong", "mark": "note", "text": "Distributivgesetz?", "why": "",
             "speech": "Wie löst man die Klammer auf?"},
            {"element": "e1", "verdict": "correct", "mark": "check", "text": "", "why": "model error", "speech": ""}]}
        model, calls = self.fake([read, judged])
        r = review.run(strokes, model=model)
        self.assertEqual(r.subject, "math")
        self.assertTrue(calls[0]["images"][0].startswith(b"\x89PNG"))
        self.assertIn("elements", calls[0]["schema"]["properties"])
        self.assertEqual(r.checked, {"e1": "wrong"})
        self.assertEqual(sorted(a.mark for a in r.accepted), ["circle", "note"])
        self.assertTrue(any("contradicts" in why for _, why in r.rejected))
        self.assertEqual(list(r.speech.values()), ["Wie löst man die Klammer auf?"])
        self.assertTrue(r.strokes)


class Help(unittest.TestCase):
    def test_question_on_the_page_gets_a_help_note(self):
        from inkpartner import agent
        els = [Element(id="q", kind="formula", bbox=[300, 160, 960, 410], text="(3x+4y)^3 = ?", confidence=0.9)]
        self.assertTrue(agent.asks_for_help(els[0]))
        props = [(plan.Action("q", "help", "note",
                              text="Binom hoch 3: Pascal-Dreieck 1 3 3 1 - welche Potenzen von 3x und 4y?"), "")]
        r = review.run([], subject="math", elements=els, proposals=props)
        self.assertEqual([a.verdict for a in r.accepted], ["help"])
        self.assertEqual({s["color"] for s in r.strokes}, {"blue"})
        ys = sorted({round(s["points"][0][1]) for s in r.strokes})
        self.assertGreater(ys[-1] - ys[0], 60)               # wrapped onto more than one line

    def test_no_help_when_nobody_asked(self):
        els = [Element(id="t", kind="formula", bbox=[300, 160, 960, 260], text="3(x+2)=15", confidence=0.9)]
        r = plan.validate([plan.Action("t", "help", "note", text="Klammer aufloesen")], els, profiles.get("math"))
        self.assertEqual(r.accepted, [])
        self.assertIn("nobody asked", r.rejected[0][1])
        els.append(Element(id="q", kind="text", bbox=[300, 300, 960, 400], text="das macht mir Probleme", confidence=0.9))
        r = plan.validate([plan.Action("t", "help", "note", text="Klammer aufloesen")], els, profiles.get("math"))
        self.assertEqual(len(r.accepted), 1)

    def test_help_only_at_the_question_and_once(self):
        els = [Element("a", "formula", [300, 100, 900, 180], "(a+b)^2=a^2+2ab+b^2", confidence=.95),
               Element("t", "formula", [300, 260, 900, 400], "(3x+4y)^3 =", confidence=.95),
               Element("q", "text", [950, 250, 1700, 330], "das macht mir Probleme", confidence=.95),
               Element("z", "formula", [100, 1500, 700, 1700], "(z+x)^4 =>", confidence=.95)]
        acts = [plan.Action(i, "help", "note", text="Hinweis") for i in ("a", "t", "q", "z")]
        r = plan.validate(acts, els, profiles.get("math"))
        self.assertEqual(len(r.accepted), 1)
        self.assertIn(r.accepted[0].element, {"t", "q"})

    def test_uncertain_reading_gets_no_verdict_from_sympy(self):
        els = [el("a", "x^2+3x=1", 100), el("b", "1+5/4 = 4/4+9/4 = 13/4", 200, confidence=0.5)]
        self.assertEqual(mathcheck.check_steps(els), {})

    def test_help_must_be_a_note(self):
        els = [Element(id="q", kind="formula", bbox=[300, 160, 960, 410], text="x=?", confidence=0.9)]
        r = plan.validate([plan.Action("q", "help", "circle")], els, profiles.get("math"))
        self.assertEqual(r.accepted, [])


class Models(unittest.TestCase):
    def test_chain_falls_back_and_says_why(self):
        from inkpartner import models

        class Broken:
            name = "ollama:x"

            def json(self, *a):
                raise ConnectionError("ollama not running")

        class Works:
            name = "gemini:y"

            def json(self, *a):
                return {"ok": 1}
        c = models.Chain([Broken(), Works()])
        self.assertEqual(c.json([], "", {}), {"ok": 1})
        self.assertEqual(c.used, "gemini:y")
        self.assertIn("ollama not running", c.errors[0])

    def test_json_is_found_inside_chatter(self):
        from inkpartner import models
        self.assertEqual(models._loads('Sure!\n```json\n{"a": 1}\n```'), {"a": 1})


class Demo(unittest.TestCase):
    def test_demo_builds(self):
        from inkpartner import demo
        strokes, ink, rounds = demo.build()
        self.assertTrue(ink)
        math = rounds[0]
        self.assertNotIn(("m3", "correct"), [(a.element, a.verdict) for a in math.accepted])  # never green
        self.assertNotIn(("m3", "wrong"), [(a.element, a.verdict) for a in math.accepted])    # cause marked once
        self.assertNotIn("m4", [a.element for a in math.accepted])  # uncertain reading: no green


if __name__ == "__main__":
    unittest.main()


class FakeTabletFS:
    """A tablet as a dict of page files, with its own clock."""

    def __init__(self, files):
        from inkpartner.guards import Guard, Limits
        self.files, self.clock, self.mtimes, self.restarts = dict(files), 1000, {k: 0 for k in files}, 0
        self.host = "fake"
        self.guard = Guard(os.path.join(tempfile.mkdtemp(), "STOP"),
                           Limits(restart_quiet_s=60, restart_gap_s=0), log=lambda *a: None)
        self.monitor = None
        self.allow_restart = True
        self.pen_idle = 10_000

    def write(self, rel, data):
        self.files[rel] = data
        self.mtimes[rel] = self.clock

    def scan(self):
        return {rel: (self.mtimes[rel], len(d)) for rel, d in self.files.items()}

    def fetch(self, rel):
        return self.files[rel]

    def name(self, rel):
        return rel.split("/")[0]

    def write_file_and_restart(self, rel, data, expected, *, quiet_s):
        self.guard.check_prefix(self.files[rel], data)
        self.guard.before_restart(allowed=self.allow_restart, quiet_s=quiet_s, pen_idle_s=self.pen_idle)
        self.restarts += 1
        self.files[rel] = data


class WatcherTest(unittest.TestCase):
    def setUp(self):
        from inkpartner import watch
        self.watch = watch
        self.fix = open(FIX, "rb").read()
        self.tab = FakeTabletFS({"old/p.rm": self.fix})
        self.reviews = []
        test = self

        class Model:
            name = used = "fake"

            def json(self, images, prompt, schema):
                if "elements" in schema["properties"]:
                    test.reviews.append(1)
                    return {"subject": "math", "elements": [{"kind": "formula", "text": "(3x+4y)^3 = ?", "latex": "",
                            "box": [.2, .05, .6, .12], "confidence": .9, "legible": True, "group": "1"}]}
                return {"actions": [{"element": "e0", "verdict": "help", "mark": "note",
                                     "text": "Pascal-Dreieck: 1 3 3 1", "why": "", "speech": ""}]}

        class Pen:
            def __init__(self, tab):
                self.tab, self.sent = tab, []

            def deliver(self, strokes, rel):     # the tablet saves the injected ink into the page
                self.sent.append(strokes)
                tmp = tempfile.mkdtemp()
                src, out = os.path.join(tmp, "a.rm"), os.path.join(tmp, "b.rm")
                open(src, "wb").write(self.tab.files["new/p.rm"])
                page.append_strokes(src, strokes, out)
                self.tab.write("new/p.rm", open(out, "rb").read())
                return {"status": "delivered_unconfirmed"}
        self.pen = Pen(self.tab)
        self.w = watch.Watcher(self.tab, Model(), pen=self.pen, log=lambda *a: None,
                               state_file=os.path.join(tempfile.mkdtemp(), "s.json"))
        self.w.verify_wait_s = 0

    def test_finds_a_new_notebook_reviews_after_the_pause_and_ignores_its_own_echo(self):
        self.assertIsNone(self.w.tick())                 # start: old page is old news
        self.tab.clock = 1100
        self.tab.write("new/p.rm", self.fix)             # student opens a notebook and writes
        self.assertIsNone(self.w.tick())                 # still writing (pause not reached)
        self.tab.clock = 1106
        r = self.w.tick()
        self.assertIsNotNone(r)
        self.assertEqual(len(self.pen.sent), 1)
        self.assertEqual(self.reviews, [1])
        self.tab.clock = 1120
        self.assertIsNone(self.w.tick())                 # the agent's own ink is not a new request
        self.assertEqual(self.reviews, [1])
        self.assertEqual(self.tab.restarts, 0)

    def test_without_pen_no_restart_while_writing(self):
        self.w.pen = None
        self.w.allow_restart = True
        self.w.tick()
        self.tab.clock = 1100
        self.tab.write("new/p.rm", self.fix)
        self.tab.clock = 1106
        self.w.tick()
        self.assertEqual(self.tab.restarts, 0)           # quiet 6 s < 120 s: no restart


class Escalation(WatcherTest):
    def test_pen_fails_then_file_path_once_the_page_is_quiet(self):
        class DeadPen:
            calls = 0

            def deliver(self, strokes, rel):   # firmware update: events sent, nothing drawn
                DeadPen.calls += 1
                return {"status": "delivered_unconfirmed"}
        self.w.pen = DeadPen()
        self.w.allow_restart = True
        self.w.restart_quiet_s = 60
        self.w.restart_gap_s = 0
        self.w.tick()
        self.tab.clock = 1100
        self.tab.write("new/p.rm", self.fix)
        self.tab.clock = 1106
        self.w.tick()                                    # pen fails, verified missing -> pending
        st = self.w.pages["new/p.rm"]
        self.assertIsNotNone(st.pending)
        self.assertEqual(self.tab.restarts, 0)           # student just wrote: no restart
        self.tab.clock = 1170
        self.w.tick()                                    # quiet 70 s -> file path
        self.assertEqual(self.tab.restarts, 1)
        self.assertIsNone(st.pending)
        self.assertTrue(st.delivered)

    def test_pending_feedback_is_dropped_when_the_student_changes_the_page(self):
        class DeadPen:
            def deliver(self, strokes, rel):
                return {"status": "delivered_unconfirmed"}
        self.w.pen = DeadPen()
        self.w.allow_restart = True
        self.w.tick()
        self.tab.clock = 1100
        self.tab.write("new/p.rm", self.fix)
        self.tab.clock = 1106
        self.w.tick()
        self.tab.clock = 1150
        self.tab.write("new/p.rm", open(os.path.join(HERE, "fixtures", "Normal_A_stroke_2_layers_v3.3.2.rm"), "rb").read())
        self.w.tick()
        self.assertIsNone(self.w.pages["new/p.rm"].pending)
        self.assertEqual(self.tab.restarts, 0)

    def test_pen_rests_after_two_failures(self):
        class DeadPen:
            def deliver(self, strokes, rel):
                return {"status": "delivered_unconfirmed"}
        self.w.pen = DeadPen()
        st = page.read_strokes(FIX)
        for _ in range(2):
            self.w.pages["new/p.rm"] = self.watch.PageState((0, 0), 1000)
            self.tab.files["new/p.rm"] = self.fix
            self.w.deliver("new/p.rm", self.w.pages["new/p.rm"], FIX, self.fix, "x",
                           review.run(st, subject="math", elements=[el("q", "x=?", 100)],
                                      proposals=[(plan.Action("q", "help", "note", text="Hinweis"), "")]), 1000)
        self.assertGreater(self.w.pen_rest_until, 1000)


class RestartIsLastResort(WatcherTest):
    def test_defaults_never_restart(self):
        from inkpartner import watch
        w = watch.Watcher(self.tab, None, pen=False, log=lambda *a: None,
                          state_file=os.path.join(tempfile.mkdtemp(), "s.json"))
        self.assertFalse(w.allow_restart)
        self.assertGreaterEqual(w.restart_quiet_s, 1800)

    def test_at_most_one_restart_per_gap(self):
        self.w.allow_restart, self.w.restart_quiet_s, self.w.restart_gap_s = True, 0, 3600
        self.w.last_restart = 1000
        self.tab.write("new/p.rm", self.fix)
        st = self.watch.PageState(self.tab.scan()["new/p.rm"], 0)
        self.w.pages = {"new/p.rm": st}
        st.pending = {"strokes": marks.check([100, 100, 200, 150]), "base_sha": self.watch.sha(self.fix),
                      "speech": ""}
        for s_ in st.pending["strokes"]:
            s_["action"] = "k"
        self.w.retry_pending("new/p.rm", st, 2000)        # 1000 s after the last restart: no
        self.assertEqual(self.tab.restarts, 0)


class PenStream(unittest.TestCase):
    def test_every_stroke_touches_down_and_up_like_the_real_pen(self):
        import struct
        from inkpartner import penstream
        data = penstream.build([{"points": [[100, 100], [200, 100]]}, {"points": [[100, 200], [100, 300]]}], start=0)
        ev = [struct.unpack(penstream.FMT, data[i:i + 24]) for i in range(0, len(data), 24)]
        keys = [(c, v) for _, _, t, c, v in ev if t == penstream.EV_KEY]
        self.assertEqual(keys, [(320, 1), (330, 1), (330, 0), (320, 0)] * 2)
        times = [s * 1_000_000 + u for s, u, *_ in ev]
        self.assertEqual(times, sorted(times))
        xs = [v for _, _, t, c, v in ev if t == penstream.EV_ABS and c == penstream.ABS_X]
        self.assertEqual(min(xs), round(100 / 1620 * 11180))

    def test_densify_fills_long_segments(self):
        from inkpartner import penstream
        pts = penstream.densify([[0, 0], [100, 0]], step=4)
        self.assertGreaterEqual(len(pts), 25)
        self.assertEqual(pts[-1], [100, 0])


class Guards(unittest.TestCase):
    def setUp(self):
        from inkpartner import guards
        self.g = guards
        self.dir = tempfile.mkdtemp()
        self.t = [10_000.0]
        self.guard = guards.Guard(os.path.join(self.dir, "STOP"), clock=lambda: self.t[0], log=lambda *a: None)

    def pen_ok(self, **kw):
        args = dict(target_doc="d", target_page="p", open_page=("d", "p"), pen_idle_s=60, viewport_ok=True)
        args.update(kw)
        self.guard.before_pen(**args)

    def test_pen_refused_in_every_unsafe_situation(self):
        for kw, rule in [({"open_page": ("other", "p")}, "R-OPEN"), ({"open_page": None}, "R-OPEN"),
                         ({"pen_idle_s": 0.5}, "R-PEN-NEAR"), ({"pen_idle_s": None}, "R-PEN-NEAR"),
                         ({"viewport_ok": False}, "R-VIEWPORT")]:
            with self.assertRaises(self.g.GuardError) as c:
                self.pen_ok(**kw)
            self.assertIn(rule, str(c.exception))

    def test_pen_rate_limit(self):
        for _ in range(4):
            self.pen_ok()
        with self.assertRaises(self.g.GuardError):
            self.pen_ok()

    def test_restart_refused_by_default_and_while_active(self):
        G = self.g.GuardError
        with self.assertRaises(G):
            self.guard.before_restart(allowed=False, quiet_s=1e9, pen_idle_s=1e9)
        with self.assertRaises(G):                                   # the case of 2026-10-23: 235 s quiet
            self.guard.before_restart(allowed=True, quiet_s=235, pen_idle_s=1e9)
        with self.assertRaises(G):                                   # page quiet, but the pen was used
            self.guard.before_restart(allowed=True, quiet_s=1e9, pen_idle_s=30)
        self.guard.before_restart(allowed=True, quiet_s=1e9, pen_idle_s=1e9)
        with self.assertRaises(G):                                   # once per hour
            self.guard.before_restart(allowed=True, quiet_s=1e9, pen_idle_s=1e9)

    def test_garbage_in_the_students_layer_trips_the_kill_switch(self):
        expected = marks.underline([300, 1000, 700, 1000])
        garbage = [{"points": [[100, 720, .5], [320, 1190, .5]], "author": "user"}]   # like 2026-10-23
        with self.assertRaises(self.g.Stopped):
            self.guard.after_pen(before=[], after=garbage, expected=expected, real_pen_during=False)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "STOP")))
        with self.assertRaises(self.g.Stopped):                     # every later write is blocked
            self.pen_ok()
        with self.assertRaises(self.g.Stopped):
            self.guard.before_restart(allowed=True, quiet_s=1e9, pen_idle_s=1e9)

    def test_own_ink_and_the_students_own_writing_are_not_garbage(self):
        expected = marks.underline([300, 1000, 700, 1000])
        ours = [{**s, "author": "user", "color": "green_2"} for s in expected]
        self.assertEqual(self.guard.after_pen(before=[], after=ours, expected=expected, real_pen_during=False), [])
        theirs = [{"points": [[100, 1500, .5], [200, 1500, .5]], "author": "user"}]
        self.guard.after_pen(before=[], after=theirs, expected=expected, real_pen_during=True)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "STOP")))

    def test_file_may_only_grow(self):
        self.guard.check_prefix(b"abc", b"abcdef")
        with self.assertRaises(self.g.Stopped):
            self.guard.check_prefix(b"abc", b"abXdef")


class PenChannelIsGuarded(unittest.TestCase):
    def test_no_ssh_call_when_the_target_page_is_not_open(self):
        from inkpartner import watch, guards
        calls = []

        class T(watch.Tablet):
            def ssh(self, cmd, data=None, timeout=30):
                calls.append(cmd)
                return b""

            def open_page(self):
                return ("other-doc", "other-page")
        tab = T("fake", guard=guards.Guard(os.path.join(tempfile.mkdtemp(), "STOP"), log=lambda *a: None))
        pen = watch.PenChannel(tab)
        with self.assertRaises(guards.GuardError):
            pen.deliver(marks.underline([100, 100, 200, 120]), "doc/page.rm")
        self.assertFalse(any("/dev/input" in c for c in calls))


class Simulation(unittest.TestCase):
    """The loop end to end with a fake model: student writes, watcher reacts, scoring is right."""

    def _run(self, verdict):
        from inkpartner import sim, models, readers
        from inkpartner.elements import Element

        def reader(strokes):        # reads the true text at the true place
            lines = readers.cluster_lines([s for s in strokes if s.get("author") == "user"])
            texts = ["3(x+2)=15", "3x+2=15"]
            return "math", [Element(f"e{i}", "formula", marks.bbox_of(l), texts[i], confidence=0.95)
                            for i, l in enumerate(lines)]

        class Judge:
            name = used = "fake"

            def json(self, images, prompt, schema):
                if '"e1"' not in prompt:
                    return {"actions": []}
                return {"actions": [{"element": "e1", "verdict": verdict,
                                     "mark": "circle" if verdict == "wrong" else "check",
                                     "text": "", "why": "", "speech": ""}]}
        orig_m, orig_r = models.get, readers.get
        sc = sim.Scenario("t", "math", [sim.Line("3(x+2)=15", "ok"), sim.Line("3x+2=15", "wrong")])
        try:
            models.get = lambda spec=None: Judge()
            readers.get = lambda spec, screenshot=None: reader
            return sim.run_scenario(sc, "vlm:fake", "fake", tempfile.mkdtemp(), log=lambda *a: None)
        finally:
            models.get, readers.get = orig_m, orig_r

    def test_loop_scores_a_red_mark_on_the_wrong_step_as_hit(self):
        run = self._run("wrong")
        self.assertEqual([l["outcome"] for l in run.lines], ["ok", "hit"])
        self.assertEqual(len(run.rounds), 2)              # the agent reacted after each line

    def test_a_false_green_is_replaced_by_the_checkers_red(self):
        run = self._run("correct")       # sympy says wrong: the green is rejected, the circle comes from the rule
        self.assertEqual([l["outcome"] for l in run.lines], ["ok", "hit"])

    def test_handwriting_raises_exponents_and_slants(self):
        import random
        from inkpartner import sim
        ink = sim.handwrite("x^2", (100, 100), 80, random.Random(1))
        ys = [min(p[1] for p in s["points"]) for s in ink]
        self.assertLess(min(ys), 100)                    # the exponent sits above the line
        self.assertTrue(all(s["author"] == "user" for s in ink))


class SimScoring(unittest.TestCase):
    def test_marks_count_for_the_line_they_were_read_as_even_with_a_bad_box(self):
        from inkpartner import sim
        lines = [sim.Line("(3x+4y)^3 = ?", "help"), sim.Line("x+3=5", "wrong")]
        rounds = [{"read": ["(3x+4y)^3 = ?", "x + 3 = 5"], "boxes": [[0, 900, 10, 910], [0, 0, 10, 10]],
                   "marks": [["help", 0], ["wrong", 1]]}]
        out = sim.score_lines(lines, [[100, 100, 900, 200], [100, 300, 600, 400]], rounds)
        self.assertEqual([o.outcome for o in out], ["hit", "hit"])
        self.assertEqual([o.box_iou for o in out], [0.0, 0.0])      # the boxes miss: marks would land elsewhere

    def test_unasked_help_on_a_correct_line_is_noise(self):
        from inkpartner import sim
        out = sim.score_lines([sim.Line("2x+4=10", "ok")], [[0, 0, 1, 1]],
                              [{"read": ["2x+4=10"], "boxes": [], "marks": [["help", 0]]}])
        self.assertEqual(out[0].outcome, "noise")


class TwoReadings(unittest.TestCase):
    def test_disagreement_makes_uncertain_and_nothing_readable_makes_illegible(self):
        from inkpartner import readers
        A = lambda st: ("math", [Element("e0", "formula", [0, 0, 100, 50], "2x=8", confidence=0.95),
                                 Element("e1", "line", [0, 100, 100, 150], "mwwv", confidence=0.9)])
        B = lambda st: ("math", [Element("e0", "formula", [0, 0, 100, 50], "2x=8", confidence=0.9),
                                 Element("e1", "line", [0, 100, 100, 150], "", confidence=0.1, legible=False)])
        _, els = readers.agree(A, B, [])
        self.assertTrue(els[0].certain)
        self.assertFalse(els[1].legible)
        C = lambda st: ("math", [Element("e0", "formula", [0, 0, 100, 50], "2x=6", confidence=0.9),
                                 Element("e1", "line", [0, 100, 100, 150], "mmw", confidence=0.9)])
        _, els = readers.agree(A, C, [])
        self.assertFalse(els[0].certain)                 # 2x=8 vs 2x=6: never green

    def test_illegible_element_gets_the_wavy_line_without_the_model(self):
        els = [Element("u", "line", [100, 100, 300, 150], "", confidence=0.1, legible=False)]
        r = review.run([], subject="math", elements=els, proposals=[])
        self.assertEqual([(a.verdict, a.mark) for a in r.accepted], [("unreadable", "wavy")])


class ViewportTest(unittest.TestCase):
    def test_recovers_zoom_and_scroll_from_a_screenshot(self):
        """Make a fake device thumbnail of a zoomed, scrolled view and get the transform back."""
        import io, random
        from PIL import Image, ImageDraw
        from inkpartner import viewport, sim
        rng = random.Random(3)
        strokes = []
        for i, t in enumerate(["(a+b)^2 = a^2+2ab+b^2", "(3x+4y)^3 =", "a^3+3a^2b+3ab^2+b^3", "z^4 + x^4"]):
            strokes += sim.handwrite(t, (150, 200 + i * 260), 90, rng)
        true = viewport.Viewport(1.4, -150.0, -120.0, 1.0)
        img = Image.new("RGB", (384, 512), "white")
        d = ImageDraw.Draw(img)
        k = 384 / 1620
        for x in range(0, 384, 12):
            d.line([(x, 0), (x, 512)], fill=(215, 215, 215))       # grid paper like the device
        for s in strokes:
            d.line([((p[0] * 1.4 - 150) * k, (p[1] * 1.4 - 120) * k) for p in s["points"]], fill=(20, 20, 20), width=2)
        buf = io.BytesIO(); img.save(buf, "PNG")
        v = viewport.estimate(strokes, buf.getvalue())
        self.assertAlmostEqual(v.scale, 1.4, delta=0.03)
        self.assertLess(abs(v.ox - true.ox), 40)
        self.assertLess(abs(v.oy - true.oy), 40)
        self.assertGreater(v.score, 0.6)


class ShotReader(unittest.TestCase):
    def test_boxes_come_back_through_the_viewport(self):
        from inkpartner import readers, viewport

        class M:
            def json(self, images, prompt, schema):
                assert "screenshot" in prompt
                return {"subject": "math", "elements": [{"kind": "formula", "text": "2x=8", "latex": "",
                        "box": [0.1, 0.1, 0.5, 0.2], "confidence": 0.9, "legible": True, "group": "1"}]}
        from PIL import Image
        png = page.png_bytes(Image.new("RGB", (384, 512), "white"))
        vp = viewport.Viewport(2.0, -100.0, -50.0, 1.0)            # zoomed in x2, scrolled
        _, els = readers.read_shot(M(), png, vp)
        self.assertEqual([round(v) for v in els[0].bbox], [131, 133, 455, 241])

    def test_sim_screenshot_looks_like_the_device(self):
        from inkpartner import sim
        tab = sim.SimTablet(tempfile.mkdtemp())
        png, vp = tab.screenshot()
        from PIL import Image
        import io
        self.assertEqual(Image.open(io.BytesIO(png)).size, (384, 512))
        self.assertEqual(vp.scale, 1.0)


class Snap(unittest.TestCase):
    def test_box_snaps_to_the_ink_it_roughly_points_at(self):
        import random
        from inkpartner import sim, geometry
        rng = random.Random(2)
        a = sim.handwrite("3(x+2)=15", (200, 200), 80, rng)
        b = sim.handwrite("3x+2=15", (200, 400), 80, rng)
        true_b = marks.bbox_of(b)
        els = [Element("e0", "formula", [150, 150, 700, 330], "3(x+2)=15", confidence=.9),
               Element("e1", "formula", [260, 360, 1100, 450], "3x+2=15", confidence=.9)]   # sloppy model box
        geometry.snap(els, a + b)
        self.assertEqual([round(v) for v in els[1].bbox], [round(v) for v in true_b])
        self.assertEqual([round(v) for v in els[0].bbox], [round(v) for v in marks.bbox_of(a)])


class PenPathRound4(unittest.TestCase):
    """Writing through a zoomed / scrolled screen with a possibly stale screenshot (simpen.py)."""

    def _tab(self, view, thumb):
        import random
        from inkpartner import simpen
        from inkpartner.viewport import Viewport
        tab = simpen.ScreenTablet(tempfile.mkdtemp(), Viewport(*view, 1.0), Viewport(*thumb, 1.0))
        plan = simpen.build_page(tab, 2, random.Random(4))
        return tab, plan

    def test_a_stale_screenshot_costs_one_probe_stroke_then_the_marks_land(self):
        from inkpartner import penpath, simpen, guards
        tab, plan = self._tab((1, 0, -150), (1, 0, 0))
        before = tab.strokes()
        path = penpath.PenPath(simpen.Device(tab), wait_s=0, tries=1, sleep=lambda s: None)
        with self.assertRaises(guards.GuardError) as e:
            path.deliver(plan, "d/p.rm")
        self.assertIn("R-PROBE", str(e.exception))
        self.assertEqual(len(path.landed), 1)            # only the probe went out
        path.deliver(plan, "d/p.rm")
        states = verify.verify(plan, before, tab.strokes())
        self.assertTrue(all(v == "confirmed" for v in states.values()), states)

    def test_a_mark_off_the_screen_is_not_sent(self):
        from inkpartner import penpath, simpen, guards
        tab, plan = self._tab((2.0, -1300, -200), (2.0, -1300, -200))
        n = len(tab.strokes())
        path = penpath.PenPath(simpen.Device(tab), wait_s=0, tries=1, sleep=lambda s: None)
        with self.assertRaises(guards.GuardError) as e:
            path.deliver(plan, "d/p.rm")
        self.assertIn("R-OFFSCREEN", str(e.exception))
        self.assertEqual(len(tab.strokes()), n)

    def test_the_probe_is_the_stroke_with_most_paper_around_it(self):
        from inkpartner import penpath
        ink = [{"points": [[100, 100], [200, 100]]}]
        near = {"points": [[210, 100], [240, 110]]}
        far = {"points": [[600, 600], [630, 610]]}
        self.assertEqual(penpath.pick_probe([near, far], ink), 1)

    def test_watcher_reads_its_own_pen_strokes_as_agent_ink(self):
        from inkpartner import simpen, penpath, readers
        from inkpartner.watch import Watcher
        from inkpartner.elements import Element
        from inkpartner.viewport import Viewport
        import random
        tab = simpen.ScreenTablet(tempfile.mkdtemp(), Viewport(1, 0, -150, 1.0), Viewport(1, 0, 0, 1.0))
        seen = []

        def reader(strokes):
            lines = readers.cluster_lines([s for s in strokes if s.get("author") == "user"])
            seen.append(len(lines))
            texts = ["3(x+2)=15", "3x+2=15"]
            return "math", [Element(f"e{i}", "formula", marks.bbox_of(l), texts[i % 2], confidence=0.95)
                            for i, l in enumerate(lines)]

        class Judge:
            name = used = "fake"

            def json(self, images, prompt, schema):
                return {"actions": []}
        pen = penpath.PenPath(simpen.Device(tab), wait_s=0, tries=1, sleep=lambda s: None)
        w = Watcher(tab, Judge(), subject="math", pen=pen, log=lambda *a: None, reader=reader,
                    judge_model=Judge(), state_file=os.path.join(tab.dir, "state.json"))
        w.verify_wait_s, w.verify_tries = 0, 1
        w.tick()
        rng = random.Random(3)
        for i, t in enumerate(["3(x+2)=15", "3x+2=15"]):
            tab.student_writes(sim_handwrite(t, (200, 220 + 180 * i), 80, rng))
        for _ in range(6):                                # review, probe misses, re-review, deliver
            tab.clock += 10
            w.tick()
        st = w.pages[tab.REL]
        self.assertTrue(st.own_sigs)                      # the probe and the marks are remembered
        self.assertTrue(all(n == 2 for n in seen), seen)  # the reader never took them for writing
        self.assertTrue(st.delivered)


def sim_handwrite(*a):
    from inkpartner import sim
    return sim.handwrite(*a)


class TutorLadder(unittest.TestCase):
    def test_level_one_is_a_question_without_the_result(self):
        from inkpartner import tutor
        out = {"speech": ["Welche binomische Formel passt zu einer Summe hoch drei?"], "note": "(a+b)^3 nutzen",
               "probe": "", "level": 1}
        c = tutor.score(out, level=1, spoilers=("27x^3",))
        self.assertTrue(c["sprechbar"] and c["auftrag"] and c["kein_ergebnis"], c)

    def test_a_spoken_formula_and_a_given_result_are_caught(self):
        from inkpartner import tutor
        out = {"speech": ["Das Ergebnis ist 27x^3 + 108x^2y."], "note": "", "probe": "", "level": 1}
        c = tutor.score(out, level=1, spoilers=("27x^3",))
        self.assertFalse(c["sprechbar"])
        self.assertFalse(c["kein_ergebnis"])

    def test_level_three_needs_a_new_task(self):
        from inkpartner import tutor
        out = {"speech": ["Satz eins und du.", "Zwei.", "Drei.", "Vier.", "Jetzt rechnest du die neue Aufgabe allein."],
               "note": "", "probe": "", "level": 3}
        self.assertFalse(tutor.score(out, level=3)["neue_aufgabe"])

    def test_explain_passes_the_level_into_the_prompt(self):
        from inkpartner import tutor
        seen = {}

        class M:
            def json(self, images, prompt, schema):
                seen["p"] = prompt
                return {"speech": ["Was ist der erste Schritt?"], "note": "", "probe": ""}
        tutor.explain(M(), "(a+b)^3 = ?", level=2)
        self.assertIn("Stufe 2 von 3", seen["p"])
