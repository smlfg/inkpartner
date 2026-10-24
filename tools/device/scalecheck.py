"""Planned vs landed mark: centre shift and size ratio, and whether a scale error about the
calibration L explains it. Live test 24.10.: circle 41/-51 px off, size 0.955; scale about the L
predicted (1019, 2692), landed (1027, 2684) - the small L measured the scale ~5 % short.
Usage: scalecheck.py LANDED_INDEX L_INDEX x0 y0 x1 y1   (bbox of the circled element)"""
import sys
sys.path.insert(0, "src")
import numpy as np
from inkpartner import watch, marks
i, j = int(sys.argv[1]), int(sys.argv[2]); bbox = [float(v) for v in sys.argv[3:7]]
t = watch.Tablet("remarkable")
op = t.open_page(); st = t.strokes(t.fetch(f"{op[0]}/{op[1]}.rm"))
landed = np.array([p[:2] for p in st[i]["points"]])
plan = np.array([p[:2] for s in marks.circle(bbox, color="red") for p in s["points"]])
pc, lc = (plan.min(0) + plan.max(0)) / 2, (landed.min(0) + landed.max(0)) / 2
k = ((landed.max(0) - landed.min(0)) / (plan.max(0) - plan.min(0))).mean()
L = np.array(st[j]["points"])[:, :2]; lcen = (L.min(0) + L.max(0)) / 2
print("centre shift", np.round(lc - pc), "size ratio", round(k, 3))
print("predicted with scale about the L", np.round(lcen + (pc - lcen) * k), "landed", np.round(lc))
