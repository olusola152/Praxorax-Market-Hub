"""An ornate gold monogram crest, drawn from scratch.

The brief was a stock template: a gold laurel crest around a circled
letter. That drawing is somebody's, so this builds the genre it belongs to
— heraldic wreath, medallion, monogram — with its own composition.

Deliberately different in structure from the reference: the wreath rises
from a single point at the base and opens upward rather than being two
mirrored wings under a crown, the leaves are cut as asymmetric blades
rather than symmetric teardrops, and the medallion is a double ring with a
gap at the bottom where the wreath enters it.

Every leaf is placed by the same function along a curve, so the thing looks
tuned rather than scattered: a wreath that is not regular reads as a mistake.

Run:  python3 tools/make_crest_logo.py <out-dir>
"""
import math
import os
import sys

W, H = 640, 680
CX, CY = 320, 300          # centre of the medallion

GOLD = (("0", "#7A5612"), ("0.22", "#C9962C"), ("0.46", "#FFE9AE"),
        ("0.68", "#D8A848"), ("1", "#8C6516"))
GOLD_DEEP = (("0", "#5E400C"), ("0.5", "#B98A24"), ("1", "#6B4A10"))


def grad(name, stops, x2="1", y2="1"):
    inner = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in stops)
    return (f'<linearGradient id="{name}" x1="0" y1="0" x2="{x2}" y2="{y2}">'
            f'{inner}</linearGradient>')


def leaf(x, y, angle, length, width, fill="url(#gold)"):
    """One blade, asymmetric: a long outer curve and a shallow inner one.

    Two different curves rather than a mirrored pair, because a leaf with
    identical sides is a shape and a leaf with a spine is a leaf.
    """
    a = math.radians(angle)
    tipx, tipy = x + length * math.cos(a), y + length * math.sin(a)
    # Control points pushed off the spine to each side.
    pa = math.radians(angle - 90)
    pb = math.radians(angle + 90)
    c1x = x + length * 0.42 * math.cos(a) + width * math.cos(pa)
    c1y = y + length * 0.42 * math.sin(a) + width * math.sin(pa)
    c2x = x + length * 0.30 * math.cos(a) + width * 0.62 * math.cos(pb)
    c2y = y + length * 0.30 * math.sin(a) + width * 0.62 * math.sin(pb)
    return (f'<path d="M {x:.1f} {y:.1f} '
            f'Q {c1x:.1f} {c1y:.1f} {tipx:.1f} {tipy:.1f} '
            f'Q {c2x:.1f} {c2y:.1f} {x:.1f} {y:.1f} Z" fill="{fill}"/>')


def wreath(side):
    """Half a wreath, hugging the outside of the medallion.

    The first attempt computed each leaf's lean from a mirrored angle and
    produced blades pointing in unrelated directions — scattered, not a
    wreath. The rule is simpler than that: a laurel leaf grows along the
    curve, tilted outward. So its direction is halfway between the tangent
    (the way the wreath is travelling) and the radius (straight out from
    the centre), and every leaf on the arc obeys it.

    `side` is +1 for the right half and -1 for the left; the left is the
    right reflected in x, which is what keeps the two halves identical.
    """
    out = []
    steps = 8
    base_r = 152                      # just outside the medallion's 132
    for i in range(steps):
        t = i / (steps - 1)
        # From low on the side (a=104) up to the shoulder (a=-44).
        a = math.radians(94 - 138 * t)
        r = base_r + 6 * math.sin(math.pi * t)     # bows out at the middle

        x = CX + side * r * math.cos(a)
        y = CY + r * math.sin(a)

        # Tangent is a-90 for decreasing a; radial is a. Halfway between.
        lean = math.degrees(a) - 45
        if side < 0:
            lean = 180 - lean                      # mirrored, not re-derived

        length = 92 - 34 * t
        out.append(leaf(x, y, lean, length, 23 - 6 * t,
                        "url(#goldDeep)" if i % 2 else "url(#gold)"))
        out.append(leaf(x, y, lean + 24 * side, length * 0.66, 15 - 3 * t))

        # A pip tucked between the blades and the ring.
        px = CX + side * (r - 20) * math.cos(a)
        py = CY + (r - 20) * math.sin(a)
        out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" '
                   f'r="{5.0 - 1.4 * t:.1f}" fill="url(#gold)"/>')
    return "\n  ".join(out)


def build(letter="P", name="PraxoraX", bg="#0B0C0D", word="#F4F2EC",
          dish_in=None, dish_out=None, with_word=True):
    # The medallion's centre has to suit the ground it sits on. Reusing the
    # dark fill on a white background gave a grey disc that looked like a
    # rendering fault rather than a design.
    dish_in = dish_in or "#2A2416"
    dish_out = dish_out or bg
    height = H if with_word else H - 150
    wordmark = (
        f'<text x="{CX}" y="{H - 44}" text-anchor="middle" '
        f'font-family="Georgia, \'Times New Roman\', serif" font-size="64" '
        f'letter-spacing="6" fill="{word}">{name}</text>') if with_word else ""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}"
     width="{W}" height="{height}" role="img" aria-label="{name}">
  <defs>
    {grad('gold', GOLD)}
    {grad('goldDeep', GOLD_DEEP, x2="0", y2="1")}
    <radialGradient id="dish">
      <stop offset="0" stop-color="{dish_in}"/>
      <stop offset="1" stop-color="{dish_out}"/>
    </radialGradient>
  </defs>
  <rect width="{W}" height="{height}" fill="{bg}"/>

  <!-- the wreath, rising from a single point at the base -->
  {wreath(1)}
  {wreath(-1)}
  <!-- where the two halves meet: a knot, not a pair of crossed blades -->
  <circle cx="{CX}" cy="{CY + 168}" r="13" fill="url(#gold)"/>
  <circle cx="{CX}" cy="{CY + 168}" r="5" fill="#0B0C0D" opacity=".5"/>

  <!-- medallion: two rings with the wreath entering at the base -->
  <circle cx="{CX}" cy="{CY}" r="132" fill="url(#dish)"/>
  <circle cx="{CX}" cy="{CY}" r="132" fill="none" stroke="url(#gold)"
          stroke-width="11" stroke-dasharray="720 110" stroke-dashoffset="-360"/>
  <circle cx="{CX}" cy="{CY}" r="110" fill="none" stroke="url(#goldDeep)"
          stroke-width="3" opacity=".9"/>

  <!-- the monogram -->
  <text x="{CX}" y="{CY + 66}" text-anchor="middle"
        font-family="Georgia, 'Times New Roman', serif" font-size="188"
        font-weight="bold" fill="url(#gold)">{letter}</text>

  <!-- a finial sitting on the ring rather than floating above it -->
  <path d="M {CX} {CY - 168} L {CX + 15} {CY - 140} L {CX} {CY - 118}
           L {CX - 15} {CY - 140} Z" fill="url(#gold)"/>
  <circle cx="{CX}" cy="{CY - 176}" r="8" fill="url(#gold)"/>

  {wordmark}
</svg>
"""


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    files = {
        "crest-dark.svg": build(),
        "crest-light.svg": build(bg="#FFFFFF", word="#14201B",
                                 dish_in="#FFFBF1", dish_out="#F3EADA"),
        "crest-mark-dark.svg": build(with_word=False),
        "crest-mark-light.svg": build(bg="#FFFFFF", with_word=False,
                                      dish_in="#FFFBF1", dish_out="#F3EADA"),
    }
    for name, svg in files.items():
        open(os.path.join(out, name), "w").write(svg)
        print(name)
