import sys, time, json
sys.path.insert(0, "src")
from inkpartner import watch, penstream, page as pm, marks, verify
t = watch.Tablet("remarkable", monitor=watch.PenMonitor("remarkable"))
time.sleep(7)
op = t.open_page(); rel = f"{op[0]}/{op[1]}.rm"
before = t.strokes(t.fetch(rel))
t.guard.before_pen(target_doc=op[0], target_page=op[1], open_page=op, pen_idle_s=t.monitor.idle_s(), viewport_ok=True)
y = float(sys.argv[1]) if len(sys.argv) > 1 else 1900.0
plan = [{"points": [[300 + 6 * i, y + (i % 2)] for i in range(50)], "action": "test"}]
start = t.ssh("date +%s").decode().strip()
t0 = time.time(); t.send([{"points": penstream.densify(s["points"])} for s in plan]); print("sent in", round(time.time() - t0, 2), "s", flush=True)
for k in range(40):
    time.sleep(3)
    log = t.ssh(f"journalctl -u xochitl --since @{start} --no-pager -o cat | grep -E 'penpoint|Scene written' | tail -n 5").decode()
    after = t.strokes(t.fetch(rel))
    st = verify.verify(plan, before, after)
    new = [s for s in after if tuple(map(tuple, s["points"])) not in {tuple(map(tuple, b["points"])) for b in before}]
    print(f"{3*(k+1)}s", st, [ [round(v) for v in marks.bbox_of([s])] for s in new], "timeout" if "penpoint" in log else "", "saved" if "Scene written" in log else "", flush=True)
    if st.get("test") == "confirmed" or new:
        break
