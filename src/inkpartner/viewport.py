"""Where is the page on the screen? Read from the tablet's own screenshot.

The Paper Pro does not let a program read the screen buffer (it sits behind the DRM driver; reading
it from the notes app's memory gives EIO, 2026-10-23). But the notes app writes a thumbnail of the
open page, `<doc>.thumbnails/<page>.png`, ~20 s after saving - and that thumbnail shows the page
*as displayed*: zoomed, scrolled, cut off at the screen edge. It is a small screenshot.

Laying the saved strokes over that picture gives the viewport: the scale and offset that map page
pixels to screen pixels. That is what pen events need (they land where the pen touches the SCREEN;
measured 2026-10-23: a line planned at page y=1500 landed at y=4255 in a zoomed, scrolled view).
"""
from __future__ import annotations

import io
from dataclasses import dataclass

SCREEN = (1620, 2160)


@dataclass
class Viewport:
    scale: float          # screen px per page px
    ox: float             # screen = page * scale + offset
    oy: float
    score: float          # 0..1: how much of the screenshot ink the page ink explains
    turn: complex = 1 + 0j  # rotation of the page on the screen (landscape: +-1j). Live test 24.10.:
                            # Quick sheets held sideways - a line sent across landed downwards

    def to_screen(self, x, y):
        z = complex(x, y) * self.turn * self.scale + complex(self.ox, self.oy)
        return z.real, z.imag

    def to_page(self, sx, sy):
        z = (complex(sx, sy) - complex(self.ox, self.oy)) / (self.turn * self.scale)
        return z.real, z.imag


def ink_mask(png: bytes, size=(192, 256)):
    """Dark or coloured pixels of the screenshot, grid lines and paper removed."""
    import numpy as np
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert("RGB").resize(size, Image.BILINEAR)
    a = np.asarray(img).astype(np.float32)
    grey = a.mean(axis=2)
    sat = a.max(axis=2) - a.min(axis=2)
    return ((grey < 120) | (sat > 60)).astype(np.float32)


def page_mask(strokes, scale: float, ox: float, oy: float, size=(192, 256), k: float | None = None,
              shift=(0.0, 0.0)):
    """Render page strokes into screen space at mask resolution k (mask px per screen px).
    `shift` moves the drawing inside the canvas (mask px), so ink left of / above the screen fits."""
    import numpy as np
    from PIL import Image, ImageDraw
    k = k or size[0] / SCREEN[0]
    img = Image.new("L", size, 0)
    d = ImageDraw.Draw(img)
    for s in strokes:
        pts = [((p[0] * scale + ox) * k + shift[0], (p[1] * scale + oy) * k + shift[1]) for p in s["points"]]
        if len(pts) > 1:
            d.line(pts, fill=255, width=2)
    return (np.asarray(img) > 0).astype(np.float32)


def estimate(strokes, png: bytes, scales=None, size=(192, 256), refine=True) -> Viewport:
    """Best (scale, offset) by FFT cross-correlation of the two ink masks, over a range of scales.
    Coarse on a small mask, then refined at the screenshot's full size with fine scale steps:
    round 4 measured 6-14 px error at zoom 1.5 from the coarse pass alone (one mask pixel = 8 screen px)."""
    import numpy as np
    if refine:
        from PIL import Image
        coarse = estimate(strokes, png, scales, size, refine=False)
        if coarse.score <= 0:
            return coarse
        full = Image.open(io.BytesIO(png)).size
        fine = [round(coarse.scale + 0.0025 * i, 4) for i in range(-12, 13)]
        return estimate(strokes, png, fine, full, refine=False)
    target = ink_mask(png, size)
    if target.sum() < 20 or not strokes:
        return Viewport(1.0, 0.0, 0.0, 0.0)
    scales = scales or [round(0.5 + 0.02 * i, 2) for i in range(101)]      # 0.5 .. 2.5
    k = size[0] / SCREEN[0]
    xs = [p[0] for s in strokes for p in s["points"]]
    ys = [p[1] for s in strokes for p in s["points"]]
    best = Viewport(1.0, 0.0, 0.0, -1.0)
    h, w = target.shape
    for sc in scales:
        px0, py0 = min(xs) * sc * k - 3, min(ys) * sc * k - 3
        W = int((max(xs) - min(xs)) * sc * k) + 7
        H = int((max(ys) - min(ys)) * sc * k) + 7
        m = page_mask(strokes, sc, 0.0, 0.0, size=(W, H), k=k, shift=(-px0, -py0))
        if m.sum() == 0:
            continue
        S = (H + h, W + w)
        corr = np.fft.irfft2(np.fft.rfft2(target, s=S) * np.conj(np.fft.rfft2(m, s=S)), s=S)
        iy, ix = np.unravel_index(np.argmax(corr), corr.shape)
        sy = iy if iy <= h else iy - S[0]
        sx = ix if ix <= w else ix - S[1]
        # normalise by both masks, or tiny page ink (small scale) would win
        overlap = corr[iy, ix] / max(1.0, (target.sum() * m.sum()) ** 0.5)
        if overlap > best.score:
            best = Viewport(sc, (sx - px0) / k, (sy - py0) / k, float(overlap))
    fit = page_mask(strokes, best.scale, best.ox, best.oy, size)
    near = np.maximum.reduce([np.roll(np.roll(fit, a, 0), b, 1) for a in (-1, 0, 1) for b in (-1, 0, 1)])
    best.score = float((near * target).sum() / max(1.0, target.sum()))
    return best


def _resample(pts, n=16):
    """n points evenly spaced along the stroke (pen reports and saved points differ in density)."""
    import math
    d = [0.0]
    for a, b in zip(pts, pts[1:]):
        d.append(d[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    if d[-1] == 0:
        return [list(pts[0][:2])] * n
    out, j = [], 0
    for k in range(n):
        t = d[-1] * k / (n - 1)
        while j < len(d) - 2 and d[j + 1] < t:
            j += 1
        f = 0 if d[j + 1] == d[j] else (t - d[j]) / (d[j + 1] - d[j])
        out.append([pts[j][0] + f * (pts[j + 1][0] - pts[j][0]), pts[j][1] + f * (pts[j + 1][1] - pts[j][1])])
    return out


def _fit(screen_strokes, page_strokes):
    """Similarity fit screen = a * page + t in complex numbers (a = scale and rotation), the rotation
    snapped to a quarter turn: the page is upright or the tablet is held sideways."""
    P, Q = [], []
    for sp, pp in zip(screen_strokes, page_strokes):
        Q += [complex(*q[:2]) for q in _resample(sp)]
        P += [complex(*p[:2]) for p in _resample(pp["points"])]
    mp, mq = sum(P) / len(P), sum(Q) / len(Q)
    var = sum(abs(p - mp) ** 2 for p in P)
    if var < 100:                                       # a dot: no scale to measure
        return None, 1e9
    a = sum((p - mp).conjugate() * (q - mq) for p, q in zip(P, Q)) / var
    if a == 0:
        return None, 1e9
    turn = min((1, 1j, -1, -1j), key=lambda u: abs(a / abs(a) - u))
    sc = sum(((p - mp) * turn).conjugate() * (q - mq) for p, q in zip(P, Q)).real / var
    if sc <= 0:
        return None, 1e9
    t = mq - mp * turn * sc
    vp = Viewport(sc, t.real, t.imag, 0.0, turn=turn)
    P = [[p.real, p.imag] for p in P]
    Q = [[q.real, q.imag] for q in Q]
    rms = (sum((vp.to_screen(p[0], p[1])[0] - q[0]) ** 2 + (vp.to_screen(p[0], p[1])[1] - q[1]) ** 2
               for p, q in zip(P, Q)) / len(P)) ** 0.5
    return vp, rms


def from_pen(screen_strokes, page_strokes, n: int = 4, max_rms: float = 8.0, max_shift: int = 6):
    """Viewport from the student's last strokes, seen twice: on the screen (pen events) and on the
    page (saved file). Pairs the last n of each; least squares for one scale and an offset.
    The file can lag behind the pen (live test 24.10.: the review came before the app had saved the
    last strokes), so the pairing is tried with the newest pen strokes left out, up to max_shift.
    None when nothing fits well (a stroke missing on one side, or a scroll in between)."""
    best = (None, 1e9)
    for shift in range(0, max_shift + 1):
        scr = screen_strokes[:len(screen_strokes) - shift] if shift else screen_strokes
        k = min(n, len(scr), len(page_strokes))
        if k < 2:                                       # one stroke fits any rotation: not a measurement
            break
        vp, rms = _fit(scr[-k:], page_strokes[-k:])
        if vp is not None and 0.3 < vp.scale < 4 and rms < best[1]:
            vp.shift = shift                            # newest pen strokes not yet in the file
            best = (vp, rms)
    vp, rms = best
    if vp is None or rms > max_rms:
        return None
    vp.score = round(1.0 - rms / max_rms, 3)
    return vp
