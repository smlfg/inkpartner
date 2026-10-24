"""What the watcher would do on the open page now - read, judge, plan - without sending anything.
Counts planned note points that would touch the student's ink (must be 0)."""
import sys, json, os, time
sys.path.insert(0, "src")
from inkpartner import watch, review, models, layout
from inkpartner.penpath import stroke_sig
t = watch.Tablet("remarkable")
op = t.open_page(); rel = f"{op[0]}/{op[1]}.rm"
p = json.load(open(os.path.expanduser("~/.cache/inkpartner/state.json"))).get(rel, {})
own = set(p.get("own_sigs", []))
page = [dict(x, author="agent") if stroke_sig(x) in own else x for x in t.strokes(t.fetch(rel))]
print("student strokes", sum(x["author"] == "user" for x in page), "agent", sum(x["author"] == "agent" for x in page))
t0 = time.time()
r = review.run(watch.focus(page), model=models.get(sys.argv[1] if len(sys.argv) > 1 else "ollama:qwen3.6:35b-a3b"),
               delivered=set(p.get("delivered", [])), page=page,
               placed=[v for k, v in p.get("verdicts", {}).items() if k in p.get("delivered", [])])
print(f"{r.subject} {len(r.elements)} elements in {time.time() - t0:.1f}s")
for e in r.elements: print("  ", e.id, [round(v) for v in e.bbox], repr(e.text), e.confidence)
for a in r.accepted: print("  ACC", a.verdict, a.mark, a.element, repr(a.text))
for a, why in r.rejected: print("  REJ", a.verdict, a.mark, a.element, why)
student = layout.Occupancy([x for x in page if x["author"] == "user"], 1700, 4000)
hits = sum(1 for s in r.strokes if s["action"].endswith(":note") for q in s["points"]
           if not student.free([q[0] - 1, q[1] - 1, q[0] + 1, q[1] + 1]))
print("planned strokes", len(r.strokes), "- note points on student ink:", hits)
