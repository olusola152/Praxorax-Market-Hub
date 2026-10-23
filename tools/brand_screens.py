"""Put the PraxoraX mark on the device screens in the stock photographs.

The photographs supplied for the site show phones displaying a generic green
tick and a laptop showing somebody else's blue page. On a page selling
PraxoraX that is the first thing a careful client notices, so the screens are
rebranded here rather than left to be explained away.

This is image compositing, not a filter. For each device the badge already on
screen is measured — its centre, its two semi-axes and its rotation, taken
from the pixels rather than guessed — the old mark is painted out with the
screen's own colour, and the seal is drawn back in through the same transform
so it sits on the device's plane instead of floating flat on top of it.

Run:  python3 tools/brand_screens.py <source-dir>
Writes into static/img/photos/.
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SEAL = os.path.join(ROOT, "static", "img", "seal.svg")
OUT = os.path.join(ROOT, "static", "img", "photos")

SEAL_GREEN = (30, 75, 58)

#: Wordmark width as a fraction of the seal's diameter, and how far to push
#: it towards the wide side of the glass. Both were set by looking at the
#: result, which is the only way to set them.
WORDMARK_WIDTH = 0.78
WORDMARK_NUDGE = 0.07
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
]


def font(size):
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def seal_image(px):
    """The seal, rendered large, as RGBA."""
    import cairosvg
    import io
    buf = cairosvg.svg2png(url=SEAL, output_width=px, output_height=px)
    return Image.open(io.BytesIO(buf)).convert("RGBA")


def measure(img, box, want_grey=True):
    """Centre, semi-axes and rotation of the badge already on the screen.

    Fitted by principal components of the badge's own pixels: the long axis
    of the spread is the long axis of the ellipse, and the extent along each
    gives its size. A circle photographed on a tilted plane is an ellipse,
    and this is the cheapest honest way to recover which one.
    """
    a = np.asarray(img.convert("RGB")).astype(int)
    x0, y0, x1, y1 = box
    sub = a[y0:y1, x0:x1]
    r, g, b = sub[..., 0], sub[..., 1], sub[..., 2]
    hi, lo = sub.max(axis=2), sub.min(axis=2)

    m = (g - r > 18) & (g - b > 18) & (g > 70)          # the green disc
    if want_grey:
        m = m | ((hi - lo < 26) & (lo > 80) & (hi < 190))   # its grey ring

    ys, xs = np.nonzero(m)
    if len(xs) < 40:
        raise SystemExit(f"only {len(xs)} badge pixels in {box} — widen the box")

    pts = np.stack([xs, ys]).astype(float)
    c = pts.mean(axis=1)
    w, v = np.linalg.eigh(np.cov(pts))
    v = v[:, np.argsort(w)[::-1]]
    proj = v.T @ (pts - c[:, None])
    sa = (proj[0].max() - proj[0].min()) / 2
    sb = (proj[1].max() - proj[1].min()) / 2
    ang = math.degrees(math.atan2(v[1, 0], v[0, 0]))
    # A principal axis is a line, not an arrow: the fit is equally happy
    # returning -10 degrees or 170. Left alone, half the time the mark comes
    # out upside down and the wordmark reads backwards. Fold the angle into
    # (-90, 90] so it always describes the same tilt the right way up.
    if ang > 90:
        ang -= 180
    elif ang <= -90:
        ang += 180
    return c[0] + x0, c[1] + y0, sa, sb, ang


def screen_colour(img, cx, cy, sa, sb, ang):
    """The screen's own colour just outside the badge.

    Sampled from a ring around it rather than assumed white: these screens
    carry a gradient, and filling with flat #fff leaves a patch that reads as
    a sticker.
    """
    a = np.asarray(img.convert("RGB")).astype(int)
    h, w = a.shape[:2]
    t = np.radians(ang)
    picks = []
    for k in np.linspace(0, 2 * math.pi, 48, endpoint=False):
        for scale in (1.45, 1.7):
            u, vv = sa * scale * math.cos(k), sb * scale * math.sin(k)
            x = int(round(cx + u * math.cos(t) - vv * math.sin(t)))
            y = int(round(cy + u * math.sin(t) + vv * math.cos(t)))
            if 0 <= x < w and 0 <= y < h:
                picks.append(a[y, x])
    picks = np.array(picks)
    # Median, so a stray dark pixel from the bezel does not drag it down.
    return tuple(int(v) for v in np.median(picks, axis=0))


def flat_plate(diameter, caption, cap_px):
    """The mark as it would look square-on: seal above, wordmark below.

    Built with the seal's centre at the centre of the canvas, because every
    transform after this one rotates about that point.
    """
    seal = seal_image(diameter)
    f = font(cap_px)

    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    tw = int(tmp.textlength(caption, font=f)) if caption else 0
    th = cap_px if caption else 0

    # The wordmark has to fit the device's screen, not merely the plate.
    # The seal was sized to the badge it replaced, which sits comfortably
    # within the glass — so the seal's own width is the budget, and the
    # measure is against `diameter`, not against the plate that holds it.
    if caption:
        limit = int(diameter * WORDMARK_WIDTH)
        if tw > limit:
            cap_px = max(10, int(cap_px * limit / tw))
            f = font(cap_px)
            tw = int(tmp.textlength(caption, font=f))
            th = cap_px

    gap = int(diameter * 0.16)
    below = diameter // 2 + gap + th          # centre -> bottom of text
    half = max(below, diameter // 2 + gap)
    W = max(int(diameter * 1.3), tw + diameter // 3)
    H = half * 2

    plate = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    plate.alpha_composite(seal, ((W - diameter) // 2, (H - diameter) // 2))
    if caption:
        d = ImageDraw.Draw(plate)
        # Nudged towards the far edge. These screens are photographed at an
        # angle, so the glass narrows going down the plate; text centred on
        # the seal loses its first letter under the bezel.
        shift = int(diameter * WORDMARK_NUDGE)
        d.text(((W - tw) // 2 + shift, H // 2 + diameter // 2 + gap),
               caption, font=f, fill=SEAL_GREEN + (255,))
    return plate


def brand(src, dst, box, caption, want_grey=True, grow=1.0, cap_ratio=0.3):
    img = Image.open(src).convert("RGB")
    cx, cy, sa, sb, ang = measure(img, box, want_grey)
    print(f"  badge centre ({cx:.0f},{cy:.0f}) axes {sa:.0f}x{sb:.0f} "
          f"angle {ang:.1f}deg")

    # 1. Paint the old mark out, with a soft edge so it does not show a seam.
    fill = screen_colour(img, cx, cy, sa, sb, ang)
    patch = Image.new("L", img.size, 0)
    pd = ImageDraw.Draw(patch)
    pad_a, pad_b = sa * 1.22, sb * 1.22
    pd.ellipse([-pad_a, -pad_b, pad_a, pad_b], fill=255)
    patch = patch.rotate(0)
    # drawn at the origin, so move it into place by rotating a small canvas
    blob = Image.new("L", (int(pad_a * 2) + 8, int(pad_b * 2) + 8), 0)
    ImageDraw.Draw(blob).ellipse([4, 4, pad_a * 2 + 4, pad_b * 2 + 4], fill=255)
    blob = blob.rotate(-ang, expand=True, resample=Image.BICUBIC)
    blob = blob.filter(ImageFilter.GaussianBlur(2.2))
    mask = Image.new("L", img.size, 0)
    mask.paste(blob, (int(cx - blob.width / 2), int(cy - blob.height / 2)))
    img = Image.composite(Image.new("RGB", img.size, fill), img, mask)

    # 2. Build the mark square-on, then squash and rotate it onto the plane.
    D = 420
    plate = flat_plate(D, caption, int(D * cap_ratio))
    sx = (2 * sa * grow) / D
    sy = (2 * sb * grow) / D
    plate = plate.resize((max(1, int(plate.width * sx)),
                          max(1, int(plate.height * sy))), Image.LANCZOS)
    plate = plate.rotate(-ang, expand=True, resample=Image.BICUBIC)

    # 3. Let the screen's own light fall across it, so it is lit like the rest
    #    of the photograph rather than pasted onto it.
    lum = sum(fill) / 3 / 255
    plate = Image.eval(plate, lambda v: int(v * (0.55 + 0.45 * lum)))

    img = img.convert("RGBA")
    img.alpha_composite(plate, (int(cx - plate.width / 2),
                                int(cy - plate.height / 2)))
    img = img.convert("RGB")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    img.save(dst, "JPEG", quality=90, optimize=True, progressive=True)
    print(f"  -> {dst}")
    return img


def soften(path, regions, radius=2.6):
    """Blur patches of invented UI text.

    The stock photographs carry text that is not words in any language. At
    full size it reads as a mistake. These screens are already shallow of
    focus, so blurring those patches to match puts them back to being
    anonymous interface rather than wrong writing.
    """
    img = Image.open(path).convert("RGB")
    for box in regions:
        patch = img.crop(box).filter(ImageFilter.GaussianBlur(radius))
        # Feathered, so the softened patch does not show its own rectangle.
        m = Image.new("L", (box[2] - box[0], box[3] - box[1]), 0)
        ImageDraw.Draw(m).rectangle([5, 5, m.width - 6, m.height - 6], fill=255)
        img.paste(patch, box[:2], m.filter(ImageFilter.GaussianBlur(4)))
    img.save(path, "JPEG", quality=90, optimize=True, progressive=True)
    print(f"  softened {len(regions)} patch(es) in {os.path.basename(path)}")


if __name__ == "__main__":
    src_dir = sys.argv[1] if len(sys.argv) > 1 else "."

    print("phone on a table:")
    brand(os.path.join(src_dir, "03ccd44b-image.jpg"),
          os.path.join(OUT, "alerts.jpg"),
          box=(170, 170, 320, 280), caption="PraxoraX", cap_ratio=0.20)

    print("phone in hand:")
    brand(os.path.join(src_dir, "c5386332-image.jpg"),
          os.path.join(OUT, "alerts-portal.jpg"),
          box=(195, 315, 255, 365), caption=None,
          want_grey=False, grow=1.35)
    soften(os.path.join(OUT, "alerts-portal.jpg"),
           [(186, 258, 320, 290), (172, 282, 320, 314), (112, 408, 300, 440)])
