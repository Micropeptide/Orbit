"""Orbit's app icon: a cobalt squircle with a white ring and its planet.

Drawn at 4x and scaled down. The squircle sits on Apple's 1024 grid (824 body, 100 margin)
so macOS shows it as it is instead of putting it on a plate of its own.
"""
import math, sys
from PIL import Image, ImageDraw, ImageFilter, ImageChops

S = 4                      # supersampling
N = 1024 * S

def lerp(a, b, t): return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(len(a)))
def hexc(h): return tuple(int(h[i:i+2], 16) for i in (1, 3, 5))

def squircle_mask(size, box, n=5.0):
    x0, y0, x1, y1 = box
    cx, cy, a, b = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    pts = []
    for i in range(2000):
        t = 2 * math.pi * i / 2000
        c, s = math.cos(t), math.sin(t)
        pts.append((cx + a * math.copysign(abs(c) ** (2 / n), c), cy + b * math.copysign(abs(s) ** (2 / n), s)))
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return m

def gradient(size, top, bottom, angle_deg=115):
    """A linear gradient across the canvas, top-left (top) to bottom-right (bottom)."""
    # drawn twice the size and cut from the middle, so the turned gradient reaches the corners
    big = Image.linear_gradient("L").resize((size * 2, size * 2)).rotate(angle_deg - 90, resample=Image.BICUBIC)
    g = big.crop((size // 2, size // 2, size // 2 + size, size // 2 + size))
    base = Image.new("RGB", (size, size), top)
    return Image.composite(Image.new("RGB", (size, size), bottom), base, g)

def make(path, top="#5287FF", bottom="#2843E4", violet="#7A55F7", margin=100, square=False, size=1024):
    """margin: the space round the squircle on the 1024 grid (100 is Apple's macOS grid;
    small for a favicon). square: an opaque full-bleed square, for iOS and maskable icons,
    which the system rounds itself."""
    body = (margin * S, margin * S, (1024 - margin) * S, (1024 - margin) * S)
    mask = Image.new("L", (N, N), 255) if square else squircle_mask(N, body)

    # the ground: cobalt, lighter at the top left, a breath of violet at the bottom right
    bg = gradient(N, hexc(top), hexc(bottom))
    glow = Image.new("L", (N, N), 0)
    ImageDraw.Draw(glow).ellipse((620 * S, 620 * S, 1180 * S, 1180 * S), fill=150)
    glow = glow.filter(ImageFilter.GaussianBlur(160 * S))
    bg = Image.composite(Image.new("RGB", (N, N), hexc(violet)), bg, glow)
    sheen = Image.new("L", (N, N), 0)
    ImageDraw.Draw(sheen).ellipse((40 * S, -380 * S, 984 * S, 430 * S), fill=46)
    sheen = sheen.filter(ImageFilter.GaussianBlur(90 * S))
    bg = Image.composite(Image.new("RGB", (N, N), (255, 255, 255)), bg, sheen)

    # the mark: a ring, broken where its planet passes, and the planet
    k = (body[2] - body[0]) / (824 * S)          # the mark was designed on the 824 body
    ox, oy = body[0] - 100 * S * k, body[1] - 100 * S * k
    cx, cy, r, w = ox + 500 * S * k, oy + 524 * S * k, 232 * S * k, 76 * S * k
    ang = math.radians(-42)                         # upper right
    px, py, pr = cx + r * math.cos(ang), cy + r * math.sin(ang), 80 * S * k
    mark = Image.new("L", (N, N), 0)
    d = ImageDraw.Draw(mark)
    d.ellipse((cx - r - w / 2, cy - r - w / 2, cx + r + w / 2, cy + r + w / 2), fill=255)
    d.ellipse((cx - r + w / 2, cy - r + w / 2, cx + r - w / 2, cy + r - w / 2), fill=0)
    gap = pr + 30 * S * k
    d.ellipse((px - gap, py - gap, px + gap, py + gap), fill=0)
    d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=255)

    # a soft shadow under the mark, in the ground's own deep blue, for a little depth
    shadow = mark.filter(ImageFilter.GaussianBlur(26 * S)).point(lambda v: int(v * 0.38))
    shadow = ImageChops.offset(shadow, 0, 18 * S)
    art = Image.composite(Image.new("RGB", (N, N), (14, 28, 120)), bg, shadow)

    # white, with the planet catching a little more light than the ring
    white = Image.new("RGB", (N, N), (255, 255, 255))
    tint = Image.linear_gradient("L").resize((N, N)).point(lambda v: int(v * 0.10))
    white = Image.composite(Image.new("RGB", (N, N), (214, 226, 255)), white, tint)
    art = Image.composite(white, art, mark)

    # onto the squircle, with the grid's own soft shadow below it
    if square:
        art.resize((size, size), Image.LANCZOS).save(path)
        return
    # scale the mark with the squircle when the margin is not the grid's
    out = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    drop = mask.filter(ImageFilter.GaussianBlur(14 * S)).point(lambda v: int(v * 0.30))
    drop = ImageChops.offset(drop, 0, 10 * S)
    out.paste((0, 0, 0, 255), (0, 0), drop)
    art_rgba = art.convert("RGBA"); art_rgba.putalpha(mask)
    out = Image.alpha_composite(out, art_rgba)
    # a hairline of light round the edge, as the system icons have
    edge = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(5)))
    edge = edge.point(lambda v: int(v * 0.22))
    hl = Image.new("RGBA", (N, N), (255, 255, 255, 0)); hl.putalpha(edge)
    out = Image.alpha_composite(out, hl)
    out.resize((size, size), Image.LANCZOS).save(path)

if __name__ == "__main__":
    # make-icon.py out.png [macos|small|square] [size]
    kind = sys.argv[2] if len(sys.argv) > 2 else "macos"
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 1024
    make(sys.argv[1] if len(sys.argv) > 1 else "icon_1024.png", size=size,
         margin={"macos": 100, "small": 24}.get(kind, 0), square=kind == "square")
