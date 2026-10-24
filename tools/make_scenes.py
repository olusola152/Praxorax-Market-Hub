"""Draw the five scenes on the public site.

One script rather than five hand-written files, because the thing that makes
a set of illustrations look deliberate is that they share a system: the same
palette, the same light direction, figures built from the same parts, the
same grain over the top. Drawn separately they drift, and a page of drifting
illustrations looks like clip art however good each one is.

The system:

  * Light falls from one source per scene, and every figure is rimmed on the
    side facing it. In 'presenting' that source is the projection screen, so
    the room is lit by the work itself.
  * Figures are silhouettes. At this size a face is either four pixels of
    mush or a cartoon, and neither belongs on a page about serious work.
    Silhouettes also sidestep the question of whose face is on the site.
  * Two grounds only: the dark deck for scenes that carry white text over
    them, the light canvas for scenes that sit inside the page.

Run:  python3 tools/make_scenes.py
"""
import math
import os

OUT = os.path.join(os.path.dirname(__file__), "..", "static", "img", "scenes")

# ---------------------------------------------------------------- palette
DEEP = "#0C1714"        # the deck ground
DEEP_2 = "#132A21"      # one step up, for walls and floors
SEAL = "#1E4B3A"        # the house green
SEAL_2 = "#2C6349"
CANVAS = "#E7EBE3"      # paper
PAPER_2 = "#DDE3D7"
BRASS = "#9A6F22"
BRASS_LIT = "#D8A848"   # brass under light
MINT = "#4FD6A0"        # the one cool accent, used sparingly
INK = "#0A1210"


_uid = [0]


def _next_id(prefix):
    _uid[0] += 1
    return f"{prefix}{_uid[0]}"


def head_and_shoulders(cx, base, scale, fill, lit=None, lit_side=1):
    """One figure, seen from behind or in profile.

    A circle and a tapered body. Everything expressive about these figures
    is in where they are placed and how they are lit, not in their shape.
    `lit` paints a rim down one side, which is what stops a row of
    silhouettes reading as a row of identical cutouts.
    """
    r = 13 * scale
    neck = base - 52 * scale
    head_y = neck - r - 3 * scale
    half = 26 * scale

    parts = []
    body = (f"M {cx - half} {base} "
            f"C {cx - half} {neck + 10 * scale}, "
            f"{cx - half * 0.72} {neck - 2 * scale}, {cx} {neck - 2 * scale} "
            f"C {cx + half * 0.72} {neck - 2 * scale}, "
            f"{cx + half} {neck + 10 * scale}, {cx + half} {base} Z")
    parts.append(f'<path d="{body}" fill="{fill}"/>')
    parts.append(f'<circle cx="{cx}" cy="{head_y}" r="{r}" fill="{fill}"/>')

    if lit:
        # The rim is a crescent, not a wedge: clip the whole silhouette and
        # lay a second, offset copy of it inside the clip. Shifting the copy
        # away from the light leaves a sliver of lit colour down the facing
        # edge — which is what a rim light actually is. Drawing it as a path
        # by hand gives a triangle pointing at nothing.
        s = lit_side
        cid = _next_id("rim")
        off = 7 * scale
        parts.append(
            f'<clipPath id="{cid}">'
            f'<path d="{body}"/>'
            f'<circle cx="{cx}" cy="{head_y}" r="{r}"/>'
            f'</clipPath>')
        parts.append(
            f'<g clip-path="url(#{cid})">'
            f'<rect x="{cx - half * 2}" y="{head_y - r * 2}" '
            f'width="{half * 4}" height="{base - head_y + r * 3}" fill="{lit}"/>'
            f'<g transform="translate({-s * off},{off * 0.35})">'
            f'<path d="{body}" fill="{fill}"/>'
            f'<circle cx="{cx}" cy="{head_y}" r="{r}" fill="{fill}"/>'
            f'</g></g>')
    return "\n    ".join(parts)


def grain(idx):
    """A little noise. Flat vector at this scale looks like a diagram."""
    return f"""
  <filter id="g{idx}" x="0" y="0" width="100%" height="100%">
    <feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="3" seed="{idx}"/>
    <feColorMatrix type="saturate" values="0"/>
  </filter>"""


def wrap(w, h, defs, body, idx):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"
     width="{w}" height="{h}" role="img">
  <defs>{defs}{grain(idx)}
  </defs>
  {body}
  <rect width="{w}" height="{h}" filter="url(#g{idx})" opacity=".05"
        style="mix-blend-mode:overlay"/>
</svg>
"""


# ============================================================== presenting
def presenting():
    """The hero. A student presenting finished work to the people who
    commissioned it, lit by the slide they are presenting."""
    w, h = 1600, 1000
    defs = f"""
    <linearGradient id="room" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{DEEP_2}"/>
      <stop offset="1" stop-color="{DEEP}"/>
    </linearGradient>
    <radialGradient id="glow" cx=".62" cy=".38" r=".52">
      <stop offset="0" stop-color="{MINT}" stop-opacity=".30"/>
      <stop offset=".55" stop-color="{SEAL_2}" stop-opacity=".12"/>
      <stop offset="1" stop-color="{DEEP}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="screen" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#F4F7F1"/>
      <stop offset="1" stop-color="#C9D6C8"/>
    </linearGradient>
    <linearGradient id="beam" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{MINT}" stop-opacity=".16"/>
      <stop offset="1" stop-color="{MINT}" stop-opacity="0"/>
    </linearGradient>"""

    # The slide being presented: a chart, because that is what gets presented.
    bars = []
    for i, (bx, bh) in enumerate([(0, 54), (1, 92), (2, 72), (3, 126), (4, 104)]):
        x = 900 + bx * 54
        colour = BRASS_LIT if bx == 3 else SEAL
        bars.append(f'<rect x="{x}" y="{420 - bh}" width="34" height="{bh}" '
                    f'rx="4" fill="{colour}" opacity=".9"/>')

    audience = []
    # Front row, close and large, backs to us. They frame the picture.
    for cx, sc, tone in ((250, 2.5, INK), (560, 2.7, INK), (1340, 2.6, INK)):
        audience.append(head_and_shoulders(cx, 1010, sc, tone,
                                           lit=SEAL_2, lit_side=1))
    # Second row, smaller and lighter: depth without clutter.
    for cx, sc in ((410, 1.7), (720, 1.6), (1180, 1.7)):
        audience.append(head_and_shoulders(cx, 830, sc, "#101F1A",
                                           lit=SEAL, lit_side=1))

    body = f"""
  <rect width="{w}" height="{h}" fill="url(#room)"/>
  <rect width="{w}" height="{h}" fill="url(#glow)"/>

  <!-- the wall the screen hangs on -->
  <rect x="820" y="150" width="700" height="330" rx="10" fill="{INK}" opacity=".55"/>
  <rect x="836" y="166" width="668" height="298" rx="6" fill="url(#screen)"/>

  <!-- what is on the slide -->
  <rect x="876" y="210" width="300" height="17" rx="8" fill="{SEAL}" opacity=".85"/>
  <rect x="876" y="243" width="186" height="11" rx="5" fill="{SEAL}" opacity=".35"/>
  <line x1="876" y1="422" x2="1464" y2="422" stroke="{SEAL}"
        stroke-opacity=".3" stroke-width="2"/>
  {"".join(bars)}
  <path d="M 1230 300 L 1290 262 L 1350 288 L 1430 222" fill="none"
        stroke="{BRASS}" stroke-width="5" stroke-linecap="round"
        stroke-linejoin="round" opacity=".9"/>
  <circle cx="1430" cy="222" r="9" fill="{BRASS}"/>

  <!-- light thrown off the screen into the room -->
  <path d="M 836 166 L 300 470 L 300 1000 L 836 464 Z" fill="url(#beam)"/>

  <!-- the presenter, rim-lit by their own slide -->
  <g>
    {head_and_shoulders(700, 760, 4.4, INK, lit=MINT, lit_side=1)}
    <path d="M 788 600 L 854 536" stroke="{INK}" stroke-width="22"
          stroke-linecap="round"/>
    <path d="M 790 598 L 852 538" stroke="{MINT}" stroke-width="7"
          stroke-linecap="round" opacity=".55"/>
  </g>

  <!-- the room -->
  {"".join(audience)}

  <!-- floor line, to sit everything on something -->
  <rect y="{h - 6}" width="{w}" height="6" fill="{BRASS}" opacity=".55"/>"""
    return wrap(w, h, defs, body, 1)


# ================================================================ teamwork
def teamwork():
    """Students mid-project. Light ground: this one sits inside the page.

    Composed low and tight. An earlier pass put the table two thirds of the
    way up and left the bottom third empty, which reads as a mistake rather
    than as space.
    """
    w, h = 1200, 760
    defs = f"""
    <linearGradient id="t-bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{DEEP_2}"/>
      <stop offset="1" stop-color="{DEEP}"/>
    </linearGradient>
    <radialGradient id="t-pool" cx=".5" cy=".62" r=".5">
      <stop offset="0" stop-color="{BRASS_LIT}" stop-opacity=".16"/>
      <stop offset="1" stop-color="{DEEP}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="t-table" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{SEAL_2}"/>
      <stop offset="1" stop-color="{SEAL}"/>
    </linearGradient>"""

    TOP = 560          # where the table top sits; everything hangs off this

    # Two behind the table facing us, one at each end turned inward.
    people = [head_and_shoulders(430, TOP + 4, 2.6, INK, lit=MINT, lit_side=-1),
              head_and_shoulders(730, TOP + 4, 2.6, INK, lit=MINT, lit_side=1),
              head_and_shoulders(196, TOP + 48, 2.9, "#0E1C17", lit=BRASS_LIT,
                                 lit_side=1),
              head_and_shoulders(1000, TOP + 48, 2.9, "#0E1C17", lit=BRASS_LIT,
                                 lit_side=-1)]

    # Open laptops, seen from behind, standing on the table.
    laptops = []
    for lx in (356, 668):
        laptops.append(
            f'<rect x="{lx + 4}" y="{TOP - 86}" width="92" height="64" rx="4" '
            f'fill="{CANVAS}"/>'
            f'<rect x="{lx + 14}" y="{TOP - 76}" width="60" height="7" rx="3" '
            f'fill="{SEAL}" opacity=".35"/>'
            f'<path d="M {lx} {TOP - 22} L {lx + 100} {TOP - 22} '
            f'L {lx + 116} {TOP} L {lx - 16} {TOP} Z" fill="#6E8878"/>')

    body = f"""
  <rect width="{w}" height="{h}" fill="url(#t-bg)"/>
  <rect width="{w}" height="{h}" fill="url(#t-pool)"/>

  <!-- a window at night, so the light has somewhere to come from -->
  <rect x="74" y="76" width="216" height="196" rx="8" fill="{SEAL_2}" opacity=".3"/>
  <line x1="182" y1="76" x2="182" y2="272" stroke="{DEEP}" stroke-width="6"/>
  <line x1="74" y1="174" x2="290" y2="174" stroke="{DEEP}" stroke-width="6"/>

  <!-- their work, pinned up behind them -->
  <rect x="742" y="84" width="148" height="186" rx="6" fill="{CANVAS}" opacity=".93"/>
  <rect x="766" y="114" width="100" height="9" rx="4" fill="{SEAL}" opacity=".45"/>
  <rect x="766" y="136" width="74" height="9" rx="4" fill="{SEAL}" opacity=".3"/>
  <rect x="766" y="174" width="100" height="62" rx="4" fill="{BRASS}" opacity=".35"/>
  <rect x="918" y="84" width="148" height="186" rx="6" fill="{CANVAS}" opacity=".93"/>
  <path d="M 942 222 L 982 180 L 1016 206 L 1044 164" fill="none"
        stroke="{SEAL}" stroke-width="5" stroke-linecap="round"
        stroke-linejoin="round" opacity=".55"/>

  {"".join(people)}
  {"".join(laptops)}

  <!-- paper between them, and a pencil left across it -->
  <g transform="rotate(-4 532 {TOP - 26})">
    <rect x="474" y="{TOP - 46}" width="126" height="40" rx="4" fill="{CANVAS}"/>
    <rect x="492" y="{TOP - 34}" width="78" height="5" rx="2" fill="{SEAL}" opacity=".4"/>
    <rect x="492" y="{TOP - 22}" width="52" height="5" rx="2" fill="{SEAL}" opacity=".25"/>
  </g>
  <rect x="604" y="{TOP - 24}" width="78" height="7" rx="3" fill="{BRASS}"
        transform="rotate(7 643 {TOP - 21})"/>

  <!-- the table, and the floor it stands on -->
  <rect x="96" y="{TOP}" width="1008" height="38" rx="10" fill="url(#t-table)"/>
  <rect x="96" y="{TOP + 38}" width="1008" height="12" rx="6" fill="{INK}" opacity=".22"/>
  <rect x="186" y="{TOP + 50}" width="26" height="150" fill="{INK}" opacity=".7"/>
  <rect x="988" y="{TOP + 50}" width="26" height="150" fill="{INK}" opacity=".7"/>
  <ellipse cx="600" cy="{TOP + 196}" rx="520" ry="26" fill="{INK}" opacity=".5"/>

  <rect y="{h - 5}" width="{w}" height="5" fill="{BRASS}" opacity=".5"/>"""
    return wrap(w, h, defs, body, 2)


# ================================================================== review
def review():
    """A lecturer going through a submission and marking it up."""
    w, h = 1200, 900
    defs = f"""
    <linearGradient id="r-bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{CANVAS}"/>
      <stop offset="1" stop-color="{PAPER_2}"/>
    </linearGradient>"""

    # Three review marks: two passed, one sent back. The brass one is the point.
    rows = []
    for i, state in enumerate(("ok", "ok", "back", "wait")):
        y = 300 + i * 96
        tone = {"ok": SEAL, "back": BRASS, "wait": "#A9B6AA"}[state]
        rows.append(f"""
  <rect x="560" y="{y}" width="500" height="72" rx="8" fill="#FFFFFF" opacity=".92"/>
  <rect x="560" y="{y}" width="6" height="72" rx="3" fill="{tone}"/>
  <rect x="592" y="{y + 20}" width="{250 - i * 28}" height="10" rx="5"
        fill="{SEAL}" opacity=".5"/>
  <rect x="592" y="{y + 42}" width="{170 - i * 20}" height="8" rx="4"
        fill="{SEAL}" opacity=".28"/>
  <circle cx="1012" cy="{y + 36}" r="15" fill="{tone}" opacity=".16"/>
  <circle cx="1012" cy="{y + 36}" r="6" fill="{tone}"/>""")

    body = f"""
  <rect width="{w}" height="{h}" fill="url(#r-bg)"/>

  <!-- the lecturer, in profile, facing the work -->
  {head_and_shoulders(280, 760, 4.6, SEAL, lit=BRASS, lit_side=1)}
  <path d="M 388 600 L 470 640" stroke="{SEAL}" stroke-width="24"
        stroke-linecap="round"/>
  <path d="M 462 636 L 520 660" stroke="{BRASS}" stroke-width="12"
        stroke-linecap="round"/>

  <!-- what they are reading -->
  <rect x="528" y="236" width="564" height="500" rx="14" fill="{SEAL}" opacity=".07"/>
  <rect x="560" y="264" width="300" height="14" rx="7" fill="{SEAL}" opacity=".6"/>
  {"".join(rows)}

  <rect y="{h - 5}" width="{w}" height="5" fill="{BRASS}" opacity=".5"/>"""
    return wrap(w, h, defs, body, 3)


# =================================================================== brief
def brief():
    """A company writing up the work they need done."""
    w, h = 1200, 900
    defs = f"""
    <linearGradient id="b-bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{DEEP_2}"/>
      <stop offset="1" stop-color="{DEEP}"/>
    </linearGradient>
    <radialGradient id="b-pool" cx=".66" cy=".44" r=".5">
      <stop offset="0" stop-color="{MINT}" stop-opacity=".14"/>
      <stop offset="1" stop-color="{DEEP}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="board" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FAFBF7"/>
      <stop offset="1" stop-color="#E4EADF"/>
    </linearGradient>"""

    notes = []
    for i, (nx, ny, tone) in enumerate([
            (660, 230, BRASS), (812, 254, SEAL), (964, 226, BRASS),
            (676, 372, SEAL), (828, 396, BRASS), (980, 368, SEAL)]):
        notes.append(
            f'<g transform="rotate({-5 + i * 2} {nx + 54} {ny + 44})">'
            f'<rect x="{nx}" y="{ny}" width="108" height="88" rx="5" '
            f'fill="{tone}" opacity=".18"/>'
            f'<rect x="{nx + 16}" y="{ny + 24}" width="72" height="8" rx="4" '
            f'fill="{tone}" opacity=".75"/>'
            f'<rect x="{nx + 16}" y="{ny + 44}" width="50" height="8" rx="4" '
            f'fill="{tone}" opacity=".45"/></g>')

    body = f"""
  <rect width="{w}" height="{h}" fill="url(#b-bg)"/>
  <rect width="{w}" height="{h}" fill="url(#b-pool)"/>

  <!-- the board the brief is being built on -->
  <rect x="604" y="150" width="520" height="430" rx="12" fill="url(#board)"/>
  <rect x="604" y="150" width="520" height="430" rx="12" fill="none"
        stroke="{SEAL}" stroke-opacity=".18" stroke-width="2"/>
  <rect x="640" y="184" width="214" height="13" rx="6" fill="{SEAL}" opacity=".6"/>
  {"".join(notes)}
  <rect x="604" y="604" width="520" height="8" rx="4" fill="{SEAL}" opacity=".12"/>

  <!-- the person writing it -->
  {head_and_shoulders(320, 760, 4.8, INK, lit=BRASS_LIT, lit_side=1)}
  <path d="M 436 596 L 540 540" stroke="{INK}" stroke-width="26"
        stroke-linecap="round"/>
  <circle cx="556" cy="532" r="15" fill="{BRASS_LIT}"/>

  <rect y="{h - 5}" width="{w}" height="5" fill="{BRASS}" opacity=".5"/>"""
    return wrap(w, h, defs, body, 4)


# ============================================================= certificate
def certificate():
    """The closing band: what the work was all for. Dark ground, white text
    goes over this one."""
    w, h = 1600, 760
    defs = f"""
    <linearGradient id="c-bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{DEEP}"/>
      <stop offset="1" stop-color="{DEEP_2}"/>
    </linearGradient>
    <radialGradient id="c-glow" cx=".5" cy=".46" r=".46">
      <stop offset="0" stop-color="{BRASS_LIT}" stop-opacity=".26"/>
      <stop offset="1" stop-color="{DEEP}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="c-paper" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FAFBF7"/>
      <stop offset="1" stop-color="#DCE4D8"/>
    </linearGradient>"""

    # Four signatures: the chain that produced the record. Student, lecturer,
    # university, company — in that order, which is the order they sign.
    sigs = []
    for i in range(4):
        x = 452 + i * 62
        sigs.append(f'<rect x="{x}" y="474" width="42" height="5" rx="2" '
                    f'fill="{SEAL}" opacity=".45"/>'
                    f'<circle cx="{x + 21}" cy="452" r="10" fill="{BRASS}" '
                    f'opacity="{0.9 - i * 0.13}"/>')

    # The document sits left of centre and the graduate stands to its right,
    # rather than in front of it. A figure overlapping the certificate hides
    # the one thing the picture is about.
    body = f"""
  <rect width="{w}" height="{h}" fill="url(#c-bg)"/>
  <rect width="{w}" height="{h}" fill="url(#c-glow)"/>

  <!-- the record itself -->
  <g transform="rotate(-2.5 560 350)">
    <rect x="392" y="150" width="336" height="384" rx="8" fill="{INK}" opacity=".5"
          transform="translate(10,14)"/>
    <rect x="392" y="150" width="336" height="384" rx="8" fill="url(#c-paper)"/>
    <rect x="432" y="198" width="190" height="13" rx="6" fill="{SEAL}" opacity=".65"/>
    <rect x="432" y="230" width="126" height="9" rx="4" fill="{SEAL}" opacity=".35"/>
    <rect x="432" y="268" width="256" height="7" rx="3" fill="{SEAL}" opacity=".18"/>
    <rect x="432" y="286" width="224" height="7" rx="3" fill="{SEAL}" opacity=".18"/>
    <circle cx="560" cy="368" r="42" fill="none" stroke="{SEAL}"
            stroke-width="5" opacity=".5"/>
    <circle cx="560" cy="368" r="16" fill="{BRASS}"/>
    {"".join(sigs)}
  </g>

  <!-- the graduate, beside it, not over it -->
  {head_and_shoulders(1046, 760, 5.4, INK, lit=BRASS, lit_side=-1)}

  <!-- two more behind, for a cohort rather than one person -->
  {head_and_shoulders(1300, 760, 3.6, "#0E1C17", lit=SEAL_2, lit_side=-1)}
  {head_and_shoulders(196, 760, 3.6, "#0E1C17", lit=SEAL_2, lit_side=1)}

  <rect y="{h - 6}" width="{w}" height="6" fill="{BRASS}" opacity=".6"/>"""
    return wrap(w, h, defs, body, 5)


# =================================================================== alerts
def alerts():
    """A phone showing a confirmation.

    The fallback behind the photographed, branded handset. It exists so that
    deleting that photograph degrades to a drawing rather than to a broken
    image: every slot must always resolve to a file that is actually there.
    """
    w, h = 1200, 760
    defs = f"""
    <linearGradient id="a-bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{DEEP_2}"/>
      <stop offset="1" stop-color="{DEEP}"/>
    </linearGradient>
    <radialGradient id="a-pool" cx=".5" cy=".5" r=".46">
      <stop offset="0" stop-color="{BRASS_LIT}" stop-opacity=".2"/>
      <stop offset="1" stop-color="{DEEP}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="glass" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FAFBF7"/>
      <stop offset="1" stop-color="#E2E8DD"/>
    </linearGradient>"""

    # The seal, drawn the same way it is in static/img/seal.svg: four arcs
    # around a brass centre.
    cx, cy, r = 600, 332, 62
    k = 0.3928
    arcs = []
    for rot in (0, 90, 180, 270):
        a0 = math.radians(rot + 12)
        a1 = math.radians(rot + 78)
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        arcs.append(f'<path d="M {x0:.1f} {y0:.1f} A {r} {r} 0 0 1 '
                    f'{x1:.1f} {y1:.1f}" fill="none" stroke="{SEAL}" '
                    f'stroke-width="14" stroke-linecap="round"/>')

    body = f"""
  <rect width="{w}" height="{h}" fill="url(#a-bg)"/>
  <rect width="{w}" height="{h}" fill="url(#a-pool)"/>

  <!-- the handset -->
  <rect x="408" y="70" width="384" height="700" rx="46" fill="{INK}"/>
  <rect x="424" y="86" width="352" height="668" rx="34" fill="url(#glass)"/>
  <rect x="556" y="104" width="88" height="10" rx="5" fill="{INK}" opacity=".35"/>

  <!-- the mark on the screen -->
  {"".join(arcs)}
  <circle cx="{cx}" cy="{cy}" r="26" fill="{BRASS}"/>

  <!-- what the confirmation says -->
  <rect x="488" y="452" width="224" height="16" rx="8" fill="{SEAL}" opacity=".75"/>
  <rect x="520" y="488" width="160" height="11" rx="5" fill="{SEAL}" opacity=".4"/>
  <rect x="472" y="556" width="256" height="54" rx="12" fill="{SEAL}" opacity=".14"/>
  <rect x="512" y="574" width="176" height="12" rx="6" fill="{SEAL}" opacity=".5"/>

  <rect y="{h - 6}" width="{w}" height="6" fill="{BRASS}" opacity=".6"/>"""
    return wrap(w, h, defs, body, 6)



# ==================================================================== fleet
def fleet():
    """An aircraft above cloud, in the house palette.

    The fallback behind the photographed plane. It exists for the same
    reason every other fallback does: removing a photograph should leave a
    drawing, not a broken image.

    Drawn from directly ahead and slightly below, because a side-on
    aeroplane is a long thin shape that leaves a card mostly empty.
    """
    w, h = 1400, 820
    defs = f"""
    <linearGradient id="f-sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{DEEP}"/>
      <stop offset="0.55" stop-color="{DEEP_2}"/>
      <stop offset="1" stop-color="#1B3A2E"/>
    </linearGradient>
    <radialGradient id="f-sun" cx=".74" cy=".2" r=".42">
      <stop offset="0" stop-color="{BRASS_LIT}" stop-opacity=".40"/>
      <stop offset="1" stop-color="{DEEP}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="f-body" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#F6F8F3"/>
      <stop offset="0.62" stop-color="#C8D2C9"/>
      <stop offset="1" stop-color="#7E8C84"/>
    </linearGradient>
    <linearGradient id="f-wing" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#8D9A91"/>
      <stop offset="0.5" stop-color="#E8EDE6"/>
      <stop offset="1" stop-color="#8D9A91"/>
    </linearGradient>"""

    CX, CY = 700, 430
    clouds = []
    for cx, cy, rx, ry, op in ((230, 690, 260, 54, .20), (640, 740, 330, 62, .26),
                               (1120, 700, 290, 56, .18), (900, 780, 380, 70, .30),
                               (380, 760, 300, 58, .24)):
        clouds.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" '
                      f'fill="{CANVAS}" opacity="{op}"/>')

    return wrap(w, h, defs, f"""
  <rect width="{w}" height="{h}" fill="url(#f-sky)"/>
  <rect width="{w}" height="{h}" fill="url(#f-sun)"/>
  {''.join(clouds)}

  <!-- wings, swept back from the fuselage -->
  <path d="M {CX - 26} {CY + 6} L {CX - 540} {CY + 92} L {CX - 520} {CY + 118}
           L {CX - 20} {CY + 46} Z" fill="url(#f-wing)"/>
  <path d="M {CX + 26} {CY + 6} L {CX + 540} {CY + 92} L {CX + 520} {CY + 118}
           L {CX + 20} {CY + 46} Z" fill="url(#f-wing)"/>

  <!-- engines -->
  <ellipse cx="{CX - 250}" cy="{CY + 72}" rx="44" ry="30" fill="{INK}"/>
  <ellipse cx="{CX - 250}" cy="{CY + 72}" rx="30" ry="19" fill="{BRASS}"/>
  <ellipse cx="{CX + 250}" cy="{CY + 72}" rx="44" ry="30" fill="{INK}"/>
  <ellipse cx="{CX + 250}" cy="{CY + 72}" rx="30" ry="19" fill="{BRASS}"/>

  <!-- fuselage and nose -->
  <path d="M {CX} {CY - 150}
           C {CX + 58} {CY - 140} {CX + 76} {CY - 40} {CX + 76} {CY + 40}
           C {CX + 76} {CY + 104} {CX + 44} {CY + 140} {CX} {CY + 140}
           C {CX - 44} {CY + 140} {CX - 76} {CY + 104} {CX - 76} {CY + 40}
           C {CX - 76} {CY - 40} {CX - 58} {CY - 140} {CX} {CY - 150} Z"
        fill="url(#f-body)"/>

  <!-- tail fin, carrying the mark's colours -->
  <path d="M {CX} {CY - 150} L {CX + 16} {CY - 268} L {CX - 16} {CY - 268} Z"
        fill="{INK}"/>
  <circle cx="{CX}" cy="{CY - 218}" r="15" fill="{BRASS_LIT}"/>

  <!-- a brass stripe down the flank -->
  <path d="M {CX - 70} {CY + 10} L {CX + 70} {CY + 10}" stroke="{BRASS}"
        stroke-width="7" opacity=".85"/>

  <!-- windows -->
  <ellipse cx="{CX}" cy="{CY - 92}" rx="40" ry="17" fill="{SEAL}" opacity=".85"/>

  <rect y="{h - 6}" width="{w}" height="6" fill="{BRASS}" opacity=".6"/>""", 8)


SCENES = {"presenting": presenting, "teamwork": teamwork, "review": review,
          "brief": brief, "certificate": certificate, "alerts": alerts, "fleet": fleet}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, fn in SCENES.items():
        path = os.path.join(OUT, name + ".svg")
        with open(path, "w") as fh:
            fh.write(fn())
        print(f"{name:14} {os.path.getsize(path):6,} bytes")
