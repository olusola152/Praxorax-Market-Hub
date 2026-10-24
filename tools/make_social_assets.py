"""Profile pictures and cover images for PraxoraX's social accounts.

Every platform wants the same two things at different sizes: a square mark
and a wide banner. Generated from the same seal and palette the site uses,
so the accounts look like the product rather than like something made in a
hurry in Canva.

Run:  python3 tools/make_social_assets.py <output-dir>
"""
import io
import os
import sys

import cairosvg
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SEAL = os.path.join(ROOT, "static", "img", "seal.svg")

SEAL_GREEN = (30, 75, 58)
NIGHT = (12, 23, 20)
BRASS = (154, 111, 34)
GOLD = (216, 168, 72)
CANVAS = (231, 235, 227)

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"]
FONTS_PLAIN = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]


def font(size, plain=False):
    for path in (FONTS_PLAIN if plain else FONTS):
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def seal(px, light=False):
    """The mark, rendered at any size. `light` recolours it for dark grounds."""
    svg = open(SEAL).read()
    if light:
        svg = svg.replace("#1E4B3A", "#E7EFE9").replace("#9A6F22", "#D8A848")
    buf = cairosvg.svg2png(bytestring=svg.encode(), output_width=px,
                           output_height=px)
    return Image.open(io.BytesIO(buf)).convert("RGBA")


def avatar(size=1000):
    """Square profile picture.

    One file at 1000px rather than one per platform: every network wants a
    square and downsizes it itself, and a set of near-identical files is a
    set of files to keep in step.
    """
    img = Image.new("RGB", (size, size), NIGHT)
    d = ImageDraw.Draw(img)
    # A brass ring just inside the edge, so the mark reads as a badge even
    # when a platform crops it to a circle.
    pad = int(size * 0.045)
    d.ellipse([pad, pad, size - pad, size - pad], outline=GOLD,
              width=max(2, size // 160))
    mark = seal(int(size * 0.56), light=True)
    img.paste(mark, ((size - mark.width) // 2, (size - mark.height) // 2), mark)
    return img


def banner(w, h, tagline="Real projects. Supervised practice."):
    """Wide cover image, composed for the centre to survive cropping."""
    img = Image.new("RGB", (w, h), NIGHT)
    d = ImageDraw.Draw(img)

    # A soft pool of brass behind the mark, so the band is not a flat slab.
    for i in range(40, 0, -1):
        r = int(h * 0.9 * i / 40)
        a = int(16 * (1 - i / 40))
        d.ellipse([w // 2 - r, h // 2 - r, w // 2 + r, h // 2 + r],
                  fill=(NIGHT[0] + a, NIGHT[1] + a // 2, NIGHT[2] + a // 3))

    mark_px = int(h * 0.42)
    mark = seal(mark_px, light=True)

    name_f = font(int(h * 0.20))
    tag_f = font(int(h * 0.085), plain=True)
    name = "PraxoraX"
    name_w = d.textlength(name, font=name_f)
    tag_w = d.textlength(tagline, font=tag_f)

    gap = int(h * 0.07)
    block = mark_px + gap + max(name_w, tag_w)
    x = (w - block) // 2

    img.paste(mark, (int(x), (h - mark_px) // 2), mark)
    tx = int(x + mark_px + gap)
    d.text((tx, h // 2 - int(h * 0.20)), name, font=name_f, fill=CANVAS)
    d.text((tx, h // 2 + int(h * 0.06)), tagline, font=tag_f, fill=GOLD)

    d.rectangle([0, h - max(3, h // 90), w, h], fill=BRASS)
    return img


SIZES = {
    # One square covers every profile picture; the platforms resize it.
    "profile-picture.png": lambda: avatar(1000),
    # Banners differ enough in shape to be worth separate files.
    "cover-x.png": lambda: banner(1500, 500),
    "cover-facebook.png": lambda: banner(1640, 624),
    "cover-linkedin.png": lambda: banner(1128, 191),
    "cover-youtube.png": lambda: banner(2048, 1152),
}

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    for name, build in SIZES.items():
        path = os.path.join(out, name)
        build().save(path, "PNG", optimize=True)
        im = Image.open(path)
        print(f"{name:24} {im.size[0]}x{im.size[1]}  "
              f"{os.path.getsize(path) // 1024}KB")
