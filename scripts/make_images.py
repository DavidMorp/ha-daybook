"""Draws the app's icon.png and logo.png (run from the repo root).

Drawn at 8x and scaled down, so lines are smooth. Two curves like the
timeline (a fast one and a slow one) above a lane of check-in marks.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

SCALE = 8
BG = (28, 28, 30, 255)
AMBER = (237, 161, 0, 255)
PINK = (212, 83, 126, 255)
MARKS = [(27, 175, 122), (98, 80, 214), (235, 104, 52), (42, 120, 214), (27, 175, 122)]


def bateman(t: float, tmax: float, half_life: float) -> float:
    ke = math.log(2) / half_life
    lo, hi = ke * 1.0001, 50.0
    for _ in range(80):  # absorption rate that peaks at tmax
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if math.log(mid / ke) / (mid - ke) > tmax else (lo, mid)
    ka = (lo + hi) / 2
    return 0.0 if t <= 0 else (math.exp(-ke * t) - math.exp(-ka * t))


def curve(box, tmax, half_life, dose_h, height, hours=16.0):
    """A dose taken at `dose_h`, drawn from that moment on; `height` is the peak's share of the box."""
    x0, y0, x1, y1 = box
    ts = [dose_h + (hours - dose_h) * i / 400 for i in range(401)]
    vs = [bateman(t - dose_h, tmax, half_life) for t in ts]
    peak = max(vs)
    return [(x0 + t / hours * (x1 - x0), y1 - v / peak * height * (y1 - y0)) for t, v in zip(ts, vs)]


def draw(size, radius, plot, lane_y, mark_h, line_w, mark_w):
    w, h = (s * SCALE for s in size)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius * SCALE, fill=BG)
    box = tuple(v * SCALE for v in plot)
    lw = round(line_w * SCALE)
    for tmax, hl, dose, height, color in ((3.5, 9.0, 0.0, 1.0, PINK), (1.2, 4.0, 3.0, 0.8, AMBER)):
        pts = curve(box, tmax, hl, dose, height)
        d.line(pts, fill=color, width=lw, joint="curve")
        for px, py in (pts[0], pts[-1]):  # round caps
            d.ellipse((px - lw / 2, py - lw / 2, px + lw / 2, py + lw / 2), fill=color)
    x0, x1 = box[0], box[2]
    for i, c in enumerate(MARKS):
        cx = x0 + (x1 - x0) * (i + 0.5) / len(MARKS)
        mw, mh = mark_w * SCALE, mark_h * SCALE
        d.rounded_rectangle((cx - mw / 2, lane_y * SCALE, cx + mw / 2, lane_y * SCALE + mh), radius=mw / 2, fill=c)
    return img.resize(size, Image.LANCZOS)


def main() -> None:
    out = Path("daybook")
    draw((128, 128), 26, (22, 22, 106, 84), 96, 12, 5, 6).save(out / "icon.png")
    draw((250, 100), 18, (22, 16, 228, 66), 76, 10, 5, 7).save(out / "logo.png")


if __name__ == "__main__":
    main()
