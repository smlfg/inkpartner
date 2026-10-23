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
    def test_distributive_error_and_follow_on_steps(self):
        els = [el("a", "3(x+2)=15", 100), el("b", "3x+2=15", 200), el("c", "3x=13", 300), el("d", "x = 13/3", 400)]
        self.assertEqual(mathcheck.check_steps(els), {"b": "wrong", "c": "correct", "d": "correct"})

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


class Agent(unittest.TestCase):
    """The model calls with a fake client: request shape and parsing, no network."""

    def fake(self, payloads):
        calls = []

        def create(**kw):
            calls.append(kw)
            text = json.dumps(payloads[len(calls) - 1])
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])
        return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create))), calls

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
        client, calls = self.fake([read, judged])
        r = review.run(strokes, client=client)
        self.assertEqual(r.subject, "math")
        self.assertEqual(calls[0]["model"], "claude-opus-5-5")
        self.assertEqual(calls[0]["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(r.checked, {"e1": "wrong"})
        self.assertEqual(sorted(a.mark for a in r.accepted), ["circle", "note"])
        self.assertTrue(any("contradicts" in why for _, why in r.rejected))
        self.assertEqual(list(r.speech.values()), ["Wie löst man die Klammer auf?"])
        self.assertTrue(r.strokes)


class Demo(unittest.TestCase):
    def test_demo_builds(self):
        from inkpartner import demo
        strokes, ink, rounds = demo.build()
        self.assertTrue(ink)
        math = rounds[0]
        self.assertIn("m3", [a.element for a in math.accepted])     # sympy-proven step gets its check
        self.assertNotIn("m4", [a.element for a in math.accepted])  # uncertain reading: no green


if __name__ == "__main__":
    unittest.main()
