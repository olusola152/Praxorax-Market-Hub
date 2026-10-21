"""Regenerate every faculty tile from explicit family assignments.

Run from the project root:

    python tools/make_field_tiles.py

Adding a field: put it in FIELDS below against a family and a motif, add the
row to the `fields` table with the matching slug, and re-run. The slug is the
field name lowercased with non-alphanumerics turned to hyphens, which is what
the landing page and the brief feed both build their filename from.

Two things were wrong with the set. Normalising colour by hue had collapsed
computing and the built environment into the same teal, so eleven fields
looked alike; and the motifs had drifted off their subjects, so Software
Engineering showed broadcast rings while Medicine showed a commit graph.

Here the hue says which family a field belongs to and the drawing says what
the field actually is. Every tile sits on the same seal-green ground so the
row reads as one set.
"""
import math
import os
import random

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "static", "img", "fields")

BG1, BG2 = "#132A21", "#1F4336"

FAMILIES = {
    "computing":   "#5DA8C0",   # azure
    "engineering": "#C09C5D",   # brass
    "life":        "#5DC08A",   # jade
    "business":    "#BFC05D",   # citron
    "civic":       "#9A8FC0",   # lilac
    "media":       "#C05D92",   # rose
}

# field -> (family, motif)
FIELDS = {
    "software-engineering":      ("computing",   "graph"),
    "computer-science":          ("computing",   "graph"),
    "information-technology":    ("computing",   "graph"),
    "artificial-intelligence":   ("computing",   "network"),
    "data-science":              ("computing",   "bars"),
    "statistics":                ("computing",   "bars"),
    "cybersecurity":             ("computing",   "lock"),

    "civil-engineering":         ("engineering", "truss"),
    "mechanical-engineering":    ("engineering", "truss"),
    "architecture":              ("engineering", "plan"),
    "estate-management":         ("engineering", "plan"),
    "industrial-design":         ("engineering", "plan"),
    "electrical-engineering":    ("engineering", "circuit"),

    "medicine":                  ("life",        "pulse"),
    "nursing":                   ("life",        "pulse"),
    "biochemistry":              ("life",        "helix"),
    "microbiology":              ("life",        "helix"),
    "agriculture":               ("life",        "furrow"),

    "accounting":                ("business",    "ledger"),
    "business-administration":   ("business",    "ledger"),
    "marketing":                 ("business",    "trend"),
    "economics":                 ("business",    "trend"),

    "law":                       ("civic",       "codex"),
    "education":                 ("civic",       "codex"),

    "mass-communication":        ("media",       "broadcast"),
}

W, H = 440, 280


def label(slug):
    small = {"and", "of"}
    return " ".join(w if w in small else w.capitalize() for w in slug.split("-"))


# --------------------------------------------------------------- the motifs
# Each returns SVG for one drawing, in the accent colour, on a 440x280 field.

def graph(c, rnd):
    """A commit graph: a trunk, a branch taken, a branch merged back.

    Drawn with the square shoulders a version-control graph actually uses.
    An earlier version used long bezier swoops and read as a wavy line with
    dots on it rather than as branching work.
    """
    out = [f'<g stroke="{c}" fill="none" stroke-width="2.4" opacity=".6" '
           f'stroke-linejoin="round">',
           '<path d="M34 140 H402"/>',
           '<path d="M104 140 L128 98 H268 L292 140"/>',
           '<path d="M174 140 L198 190 H314 L338 140"/>',
           '</g>']
    out.append(f'<g fill="{c}">')
    for x, y, r in ((34, 140, 5), (104, 140, 6), (174, 140, 5), (292, 140, 6),
                    (338, 140, 6), (402, 140, 7),
                    (152, 98, 5), (210, 98, 5), (268, 98, 5),
                    (222, 190, 5), (272, 190, 5), (314, 190, 5)):
        out.append(f'<circle cx="{x}" cy="{y}" r="{r}" opacity=".9"/>')
    out.append('</g>')
    return "\n    ".join(out)


def network(c, rnd):
    """A layered network. Artificial intelligence."""
    cols = [(70, 4), (170, 5), (270, 5), (370, 3)]
    pts = []
    for x, n in cols:
        span = 200
        ys = [140 - span / 2 + span * i / (n - 1) for i in range(n)]
        pts.append([(x, y) for y in ys])
    out = [f'<g stroke="{c}" stroke-width="1" opacity=".3">']
    for a, b in zip(pts, pts[1:]):
        for x1, y1 in a:
            for x2, y2 in b:
                out.append(f'<path d="M{x1} {y1:.0f} L{x2} {y2:.0f}"/>')
    out.append("</g>")
    out.append(f'<g fill="{c}">')
    for col in pts:
        for x, y in col:
            out.append(f'<circle cx="{x}" cy="{y:.0f}" r="5" opacity=".85"/>')
    out.append("</g>")
    return "\n    ".join(out)


def bars(c, rnd):
    """A distribution. Data science and statistics."""
    out = []
    heights = [34, 58, 92, 128, 158, 172, 158, 128, 92, 58, 34]
    for i, h in enumerate(heights):
        x = 55 + i * 33
        out.append(f'<rect x="{x}" y="{226 - h}" width="19" height="{h}" '
                   f'fill="{c}" opacity="{0.28 + 0.045 * min(i, 10 - i):.2f}"/>')
    out.append(f'<path d="M40 228 H408" stroke="{c}" stroke-width="1.5" opacity=".5"/>')
    return "\n    ".join(out)


def lock(c, rnd):
    """A shackle and a grid of keys. Cybersecurity."""
    out = [f'<g stroke="{c}" fill="none" stroke-width="2.5" opacity=".65">',
           '<path d="M178 132 V108 a42 42 0 0 1 84 0 V132"/>',
           '</g>',
           f'<rect x="156" y="132" width="128" height="94" rx="8" fill="{c}" opacity=".22"/>',
           f'<rect x="156" y="132" width="128" height="94" rx="8" fill="none" '
           f'stroke="{c}" stroke-width="2" opacity=".6"/>',
           f'<circle cx="220" cy="172" r="9" fill="{c}" opacity=".85"/>',
           f'<path d="M220 181 V200" stroke="{c}" stroke-width="4" opacity=".85" '
           f'stroke-linecap="round"/>']
    out.append(f'<g stroke="{c}" stroke-width="1" opacity=".22">')
    for x in range(40, 420, 28):
        out.append(f'<path d="M{x} 40 V240"/>')
    out.append("</g>")
    return "\n    ".join(out)


def truss(c, rnd):
    """A bridge truss. Civil and mechanical engineering."""
    out = [f'<g stroke="{c}" fill="none" stroke-width="2.2" opacity=".6">',
           '<path d="M30 190 H410"/>', '<path d="M70 96 H370"/>']
    x = 30
    up = True
    while x < 410:
        nx = min(x + 68, 410)
        top_x = max(70, min(370, x + 34))
        out.append(f'<path d="M{x} 190 L{top_x} 96 L{nx} 190"/>')
        x = nx
        up = not up
    out.append('</g>')
    out.append(f'<g fill="{c}" opacity=".8">')
    for px in range(30, 411, 68):
        out.append(f'<circle cx="{px}" cy="190" r="4.5"/>')
    out.append('</g>')
    out.append(f'<g stroke="{c}" stroke-width="1.4" opacity=".3">')
    out.append('<path d="M30 206 H410"/><path d="M30 216 H410"/>')
    out.append('</g>')
    return "\n    ".join(out)


def plan(c, rnd):
    """A floor plan. Architecture, estate management, industrial design."""
    out = [f'<g stroke="{c}" fill="none" stroke-width="2.2" opacity=".62">',
           '<path d="M60 60 H380 V220 H60 Z"/>',
           '<path d="M220 60 V140"/>',
           '<path d="M220 170 V220"/>',
           '<path d="M60 140 H160"/>',
           '<path d="M300 140 H380"/>',
           '</g>',
           f'<g stroke="{c}" fill="none" stroke-width="1.6" opacity=".4">',
           '<path d="M160 140 a30 30 0 0 1 30 -30"/>',
           '<path d="M220 170 a30 30 0 0 1 30 30"/>',
           '</g>',
           f'<g stroke="{c}" stroke-width="1" opacity=".2">']
    for x in range(40, 420, 40):
        out.append(f'<path d="M{x} 30 V250"/>')
    for y in range(40, 260, 40):
        out.append(f'<path d="M30 {y} H410"/>')
    out.append('</g>')
    return "\n    ".join(out)


def circuit(c, rnd):
    """A trace and its components. Electrical engineering."""
    out = [f'<g stroke="{c}" fill="none" stroke-width="2.2" opacity=".6">',
           '<path d="M30 96 H130 V150 H230"/>',
           '<path d="M230 150 H300 V70 H410"/>',
           '<path d="M130 150 V214 H330 V150"/>',
           '</g>']
    out.append(f'<g stroke="{c}" fill="none" stroke-width="2.4" opacity=".85">')
    out.append('<path d="M170 138 V162 M182 142 V158 M194 138 V162 M206 142 V158"/>')
    out.append('<path d="M296 196 V232 M312 196 V232"/>')
    out.append('</g>')
    out.append(f'<g fill="{c}" opacity=".9">')
    for x, y in ((30, 96), (410, 70), (130, 150), (330, 150)):
        out.append(f'<circle cx="{x}" cy="{y}" r="5"/>')
    out.append('</g>')
    return "\n    ".join(out)


def pulse(c, rnd):
    """An ECG trace. Medicine and nursing."""
    seg = ("l26 0 l9 -14 l9 46 l11 -78 l11 60 l10 -14 l30 0")
    out = [f'<path d="M20 150 {seg} {seg} {seg} {seg}" stroke="{c}" '
           f'stroke-width="2.6" fill="none" opacity=".8" stroke-linejoin="round"/>',
           f'<path d="M20 206 {seg} {seg} {seg} {seg}" stroke="{c}" '
           f'stroke-width="1.4" fill="none" opacity=".28" stroke-linejoin="round"/>',
           f'<g stroke="{c}" stroke-width="1" opacity=".16">']
    for y in range(50, 251, 25):
        out.append(f'<path d="M20 {y} H420"/>')
    out.append('</g>')
    return "\n    ".join(out)


def helix(c, rnd):
    """A double helix. Biochemistry and microbiology.

    Four turns at a modest amplitude. Three wide turns read as pointed ovals
    rather than as a twist.
    """
    out = [f'<g stroke="{c}" fill="none" stroke-width="2.4" opacity=".75">']
    a, b = [], []
    for i in range(0, 121):
        t = i / 120
        x = 36 + t * 368
        a.append(f"{x:.0f},{140 + 50 * math.sin(t * math.pi * 4):.0f}")
        b.append(f"{x:.0f},{140 - 50 * math.sin(t * math.pi * 4):.0f}")
    out.append(f'<polyline points="{" ".join(a)}"/>')
    out.append(f'<polyline points="{" ".join(b)}"/>')
    out.append('</g>')
    out.append(f'<g stroke="{c}" stroke-width="1.8" opacity=".42">')
    for i in range(4, 120, 7):
        t = i / 120
        x = 36 + t * 368
        y1 = 140 + 50 * math.sin(t * math.pi * 4)
        y2 = 140 - 50 * math.sin(t * math.pi * 4)
        if abs(y1 - y2) > 14:
            out.append(f'<path d="M{x:.0f} {y1:.0f} L{x:.0f} {y2:.0f}"/>')
    out.append('</g>')
    return "\n    ".join(out)


def furrow(c, rnd):
    """Ploughed rows running to a horizon. Agriculture."""
    out = [f'<g stroke="{c}" fill="none" stroke-width="1.8" opacity=".5">']
    for i in range(11):
        x0 = -120 + i * 86
        out.append(f'<path d="M{x0} 280 L{170 + i * 10} 104"/>')
    out.append('</g>')
    out.append(f'<g stroke="{c}" stroke-width="1.3" opacity=".3">')
    for y, in ((120,), (144,), (176,), (216,), (264,)):
        out.append(f'<path d="M0 {y} H440"/>')
    out.append('</g>')
    out.append(f'<path d="M0 104 H440" stroke="{c}" stroke-width="2" opacity=".65"/>')
    return "\n    ".join(out)


def ledger(c, rnd):
    """Ruled columns and totals. Accounting and administration."""
    out = [f'<g stroke="{c}" stroke-width="1.6" opacity=".45">']
    for y in range(64, 230, 26):
        out.append(f'<path d="M50 {y} H390"/>')
    out.append('</g>')
    out.append(f'<g stroke="{c}" stroke-width="1.6" opacity=".55">')
    out.append('<path d="M50 56 V230"/><path d="M250 56 V230"/><path d="M320 56 V230"/>')
    out.append('</g>')
    out.append(f'<g fill="{c}" opacity=".6">')
    rnd.seed(7)
    for i, y in enumerate(range(52, 222, 26)):
        w = rnd.choice((70, 96, 120, 150))
        out.append(f'<rect x="62" y="{y}" width="{w}" height="7" rx="3"/>')
        out.append(f'<rect x="{336 + (40 - rnd.choice((18, 26, 34)))}" y="{y}" '
                   f'width="{rnd.choice((18, 26, 34))}" height="7" rx="3"/>')
    out.append('</g>')
    out.append(f'<path d="M320 222 H390" stroke="{c}" stroke-width="2.6" opacity=".85"/>')
    return "\n    ".join(out)


def trend(c, rnd):
    """A line finding its way up. Marketing and economics."""
    pts = [(40, 210), (90, 186), (140, 196), (190, 152), (240, 164),
           (290, 118), (340, 128), (400, 72)]
    poly = " ".join(f"{x},{y}" for x, y in pts)
    area = f"M40 236 " + " ".join(f"L{x} {y}" for x, y in pts) + " L400 236 Z"
    out = [f'<path d="{area}" fill="{c}" opacity=".16"/>',
           f'<polyline points="{poly}" stroke="{c}" stroke-width="2.8" fill="none" '
           f'opacity=".85" stroke-linejoin="round" stroke-linecap="round"/>',
           f'<g fill="{c}" opacity=".9">']
    for x, y in pts:
        out.append(f'<circle cx="{x}" cy="{y}" r="4.5"/>')
    out.append('</g>')
    out.append(f'<path d="M40 236 H400" stroke="{c}" stroke-width="1.5" opacity=".5"/>')
    return "\n    ".join(out)


def codex(c, rnd):
    """Stacked statutes, each one shorter than the last. Law and education."""
    out = []
    for i in range(7):
        y = 58 + i * 26
        w = (300, 262, 288, 210, 276, 238, 180)[i]
        out.append(f'<rect x="70" y="{y}" width="{w}" height="8" rx="4" '
                   f'fill="{c}" opacity="{0.62 - i * 0.055:.2f}"/>')
    out.append(f'<path d="M50 44 V254" stroke="{c}" stroke-width="3" opacity=".8"/>')
    out.append(f'<path d="M62 44 V254" stroke="{c}" stroke-width="1.4" opacity=".4"/>')
    return "\n    ".join(out)


def broadcast(c, rnd):
    """Rings leaving a transmitter. Mass communication."""
    out = []
    for i, r in enumerate((34, 60, 86, 112, 138)):
        out.append(f'<circle cx="150" cy="140" r="{r}" stroke="{c}" '
                   f'stroke-width="1.6" fill="none" opacity="{0.5 - i * 0.07:.2f}"/>')
    out.append(f'<circle cx="150" cy="140" r="13" fill="{c}" opacity=".9"/>')
    out.append(f'<path d="M150 140 L150 58" stroke="{c}" stroke-width="2.4" '
               f'opacity=".7"/>')
    out.append(f'<path d="M132 74 L150 58 L168 74" stroke="{c}" stroke-width="2.4" '
               f'fill="none" opacity=".7" stroke-linejoin="round"/>')
    return "\n    ".join(out)


MOTIFS = {
    "graph": graph, "network": network, "bars": bars, "lock": lock,
    "truss": truss, "plan": plan, "circuit": circuit, "pulse": pulse,
    "helix": helix, "furrow": furrow, "ledger": ledger, "trend": trend,
    "codex": codex, "broadcast": broadcast,
}

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"
     role="img" aria-label="{label}" preserveAspectRatio="xMidYMid slice">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{bg1}"/>
      <stop offset="100%" stop-color="{bg2}"/>
    </linearGradient>
    <clipPath id="c"><rect width="{w}" height="{h}"/></clipPath>
  </defs>
  <rect width="{w}" height="{h}" fill="url(#g)"/>
  <g clip-path="url(#c)">
    {body}
  </g>
  <rect width="{w}" height="{h}" fill="none" stroke="#FFFFFF" stroke-opacity=".08" stroke-width="2"/>
</svg>
"""

if __name__ == "__main__":
    rnd = random.Random(11)
    for slug, (family, motif) in sorted(FIELDS.items()):
        colour = FAMILIES[family]
        body = MOTIFS[motif](colour, rnd)
        svg = TEMPLATE.format(w=W, h=H, label=label(slug), bg1=BG1, bg2=BG2,
                              body=body)
        with open(os.path.join(OUT, slug + ".svg"), "w") as fh:
            fh.write(svg)
    print(f"{len(FIELDS)} field tiles written")
