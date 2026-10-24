import sys, time, json, subprocess
sys.path.insert(0, "src")
from inkpartner import watch, viewport, penstream
t = watch.Tablet("remarkable")
p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", "remarkable", "cat /dev/input/event2"], stdout=subprocess.PIPE)
r = penstream.Reader(); raw = []
import os, fcntl
fcntl.fcntl(p.stdout, fcntl.F_SETFL, os.O_NONBLOCK)
print("WRITE NOW", flush=True)
t0 = time.time()
while time.time() - t0 < 90:
    try:
        c = p.stdout.read(4096)
    except Exception:
        c = None
    if c:
        raw.append(c); r.feed(c)
    if r.strokes and time.time() - r.strokes[-1][0] > 0 and len(r.strokes) >= 2 and not r.down and time.time() - t0 > 20:
        pass
    time.sleep(0.05)
p.kill()
op = t.open_page(); rel = f"{op[0]}/{op[1]}.rm"
page = [s for s in t.strokes(t.fetch(rel)) if s["author"] == "user"]
scr = [pts for _, pts in r.strokes]
print("screen strokes", len(scr), "page strokes", len(page))
def bb(pts): xs=[q[0] for q in pts]; ys=[q[1] for q in pts]; return [round(min(xs)),round(min(ys)),round(max(xs)),round(max(ys))]
for s in scr[-3:]: print("screen", bb(s), len(s))
for s in page[-3:]: print("page  ", bb(s["points"]), len(s["points"]))
W, H = 1620, 2160
for name, f in [("id", lambda x,y:(x,y)), ("swap", lambda x,y:(y*W/H, x*H/W)), ("flipx", lambda x,y:(W-x,y)), ("flipy", lambda x,y:(x,H-y)),
                ("rot90", lambda x,y:(W - y*W/H, x*H/W)), ("rot270", lambda x,y:(y*W/H, H - x*H/W)), ("flipxy", lambda x,y:(W-x,H-y))]:
    tr = [[list(f(q[0], q[1])) for q in s] for s in scr]
    vp = viewport.from_pen(tr, page, max_rms=1e9)
    print(name, vp)
