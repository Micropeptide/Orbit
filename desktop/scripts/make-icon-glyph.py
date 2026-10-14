"""The white ring and planet alone, on a transparent 1024 canvas, for the Icon Composer layer."""
import math, sys
from PIL import Image, ImageDraw
S, N = 4, 4096
cx, cy, r, w = 498 * S, 526 * S, 282 * S, 94 * S          # relative to the full 1024 canvas
ang = math.radians(-42)
px, py, pr = cx + r * math.cos(ang), cy + r * math.sin(ang), 98 * S
m = Image.new("L", (N, N), 0); d = ImageDraw.Draw(m)
d.ellipse((cx - r - w/2, cy - r - w/2, cx + r + w/2, cy + r + w/2), fill=255)
d.ellipse((cx - r + w/2, cy - r + w/2, cx + r - w/2, cy + r - w/2), fill=0)
gap = pr + 38 * S
d.ellipse((px - gap, py - gap, px + gap, py + gap), fill=0)
d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=255)
out = Image.new("RGBA", (N, N), (255, 255, 255, 0)); out.putalpha(m)
out.resize((1024, 1024), Image.LANCZOS).save(sys.argv[1])
