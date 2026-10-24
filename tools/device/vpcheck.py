import sys
sys.path.insert(0, "src")
from inkpartner import watch, viewport
t = watch.Tablet("remarkable")
op = t.open_page()
print("open page:", op, "name:", t.name(f"{op[0]}/x") if op else None)
if op:
    rel = f"{op[0]}/{op[1]}.rm"
    st = t.strokes(t.fetch(rel))
    png = t.thumbnail(rel)
    print("strokes:", len(st), "user:", sum(s["author"] == "user" for s in st), "thumbnail bytes:", len(png or b""))
    print(t.ssh(f"cd {watch.XOCHITL} && stat -c '%y %n' {op[0]}/{op[1]}.rm {op[0]}.thumbnails/{op[1]}.png; date").decode())
    if png:
        vp = viewport.estimate([s for s in st if s["author"] == "user"], png)
        print("viewport:", vp)
