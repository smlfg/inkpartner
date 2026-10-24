"""Render the open page (newest 8 strokes red) to /tmp/inkp/diag_now.png and list the last strokes.
Live test 24.10.: showed '3+4=8' was saved and read right, but never judged (page counted as code)."""
import sys
sys.path.insert(0, "src")
from inkpartner import watch
from PIL import Image, ImageDraw
t = watch.Tablet("remarkable")
op = t.open_page()
rel = f"{op[0]}/{op[1]}.rm"
print("open page:", op, t.name(rel))
st = t.strokes(t.fetch(rel))
xs = [p[0] for s in st for p in s["points"]]; ys = [p[1] for s in st for p in s["points"]]
for i, s in enumerate(st[-14:], len(st) - 14):
    px = [p[0] for p in s["points"]]; py = [p[1] for p in s["points"]]
    print(i, s["author"], len(px), "bbox", round(min(px)), round(min(py)), round(max(px)), round(max(py)))
ox, oy = min(xs) - 20, min(ys) - 20
img = Image.new("RGB", (int(max(xs) - ox + 40), int(max(ys) - oy + 40)), "white"); d = ImageDraw.Draw(img)
for i, s in enumerate(st):
    d.line([(p[0] - ox, p[1] - oy) for p in s["points"]], fill="red" if i >= len(st) - 8 else "black", width=3)
img.thumbnail((1400, 1400)); img.save("/tmp/inkp/diag_now.png")
