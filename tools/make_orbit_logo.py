"""An orbit mark with a wordmark, drawn from scratch.

The brief was a stock template: bright tapered swooshes sweeping round a
circle. That particular arrangement is somebody's drawing, so this takes the
idea a tapered-arc orbit is built on — motion, a path travelled, something
coming round — and composes it differently.

What makes the arcs read as motion rather than as rings is that each one
tapers: thick where the movement is, thin where it leaves. An arc of even
width is a ring, and a ring is static. Each is drawn as a closed path
between two radii rather than as a stroke, because a stroke cannot taper.

Run:  python3 tools/make_orbit_logo.py <out-dir>
"""
import math
import os
import sys

SIZE = 640
CX = CY = 290

PALETTES = {
    "metal": {                      # gold, silver, black — what was asked for
        "bg": "#0B0C0D",
        "word": "#F1F3F2",
        "sweeps": [(("#8C6516", "#FFE9AE", "#C9962C"), 1.0),
                   (("#5E656B", "#F4F7F9", "#9AA2A9"), 0.95),
                   (("#6B5410", "#E3BE62", "#8C6516"), 0.8)],
        "core": ("#8C6516", "#FFE9AE", "#C9962C"),
    },
    "light": {                      # the same mark for white backgrounds
        "bg": "#FFFFFF",
        "word": "#14201B",
        "sweeps": [(("#8A6412", "#D8A848", "#A97C1C"), 1.0),
                   (("#6E757C", "#AEB6BC", "#848C93"), 0.95),
                   (("#1E4B3A", "#2F6A51", "#1E4B3A"), 0.85)],
        "core": ("#8A6412", "#D8A848", "#A97C1C"),
    },
}


def arc_path(r_out, r_in, start, end, taper=0.22):
    """One tapering crescent, as a closed path.

    Wide at `start`, narrowing towards `end`. The inner edge is walked back
    on a radius that closes on the outer one, which is what produces the
    taper; a stroked arc is the same width the whole way round and reads as
    a ring.
    """
    a0, a1 = math.radians(start), math.radians(end)
    big = 1 if abs(end - start) > 180 else 0

    ox0, oy0 = CX + r_out * math.cos(a0), CY + r_out * math.sin(a0)
    ox1, oy1 = CX + r_out * math.cos(a1), CY + r_out * math.sin(a1)
    # Inner radius at the far end rises to meet the outer edge.
    r_in_end = r_out - (r_out - r_in) * taper
    ix1, iy1 = CX + r_in_end * math.cos(a1), CY + r_in_end * math.sin(a1)
    ix0, iy0 = CX + r_in * math.cos(a0), CY + r_in * math.sin(a0)

    return (f"M {ox0:.1f} {oy0:.1f} "
            f"A {r_out} {r_out} 0 {big} 1 {ox1:.1f} {oy1:.1f} "
            f"L {ix1:.1f} {iy1:.1f} "
            f"A {r_in_end} {r_in_end} 0 {big} 0 {ix0:.1f} {iy0:.1f} Z")


def build(palette, with_word=True):
    p = PALETTES[palette]
    defs, body = [], []

    # Three sweeps at different radii and lengths, each starting where the
    # eye has just been — the gaps are what keep it from closing into a ring.
    plan = [(238, 196, -150, 95), (182, 150, 40, 265), (128, 104, 205, 400)]

    for i, ((r_out, r_in, start, end), (stops, opacity)) in enumerate(
            zip(plan, p["sweeps"])):
        name = f"sweep{i}"
        defs.append(
            f'<linearGradient id="{name}" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{stops[0]}"/>'
            f'<stop offset="0.5" stop-color="{stops[1]}"/>'
            f'<stop offset="1" stop-color="{stops[2]}"/></linearGradient>')
        body.append(f'<path d="{arc_path(r_out, r_in, start, end)}" '
                    f'fill="url(#{name})" opacity="{opacity}"/>')

    defs.append(
        f'<radialGradient id="core"><stop offset="0" stop-color="{p["core"][1]}"/>'
        f'<stop offset="0.6" stop-color="{p["core"][2]}"/>'
        f'<stop offset="1" stop-color="{p["core"][0]}"/></radialGradient>')
    body.append(f'<circle cx="{CX}" cy="{CY}" r="54" fill="url(#core)"/>')
    body.append(f'<circle cx="{CX}" cy="{CY}" r="54" fill="none" '
                f'stroke="{p["bg"]}" stroke-width="6" opacity=".45"/>')

    word = ""
    if with_word:
        word = (f'<text x="{CX}" y="{SIZE - 44}" text-anchor="middle" '
                f'font-family="Georgia, \'Times New Roman\', serif" '
                f'font-size="78" font-weight="bold" letter-spacing="2" '
                f'fill="{p["word"]}">PraxoraX</text>')

    height = SIZE if with_word else 580
    return f"""<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 {SIZE} {height}" width="{SIZE}" height="{height}" role="img"
     aria-label="PraxoraX">
  <defs>
    {chr(10).join('    ' + d for d in defs)}
  </defs>
  <rect width="{SIZE}" height="{height}" fill="{p['bg']}"/>
  {chr(10).join('  ' + b for b in body)}
  {word}
</svg>
"""


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    for pal in PALETTES:
        for word in (True, False):
            name = f"orbit-{pal}{'' if word else '-mark'}.svg"
            open(os.path.join(out, name), "w").write(build(pal, word))
            print(name)
