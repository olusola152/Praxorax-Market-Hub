"""Logo directions in gold, silver and black.

Four, because a single proposal is not a choice. Each takes a different
idea of what the mark is about, and all four are drawn to the same rules so
they can be compared fairly rather than by polish:

  * Metal is a gradient, never a flat fill. Flat #FFD700 reads as yellow
    plastic; gold is a dark edge, a bright band and a warm edge.
  * Everything must survive 24px. A logo is seen small far more often than
    large, and detail that disappears there is decoration.
  * Nothing relies on colour alone, so the one-colour version still works
    on an invoice or a stamp.

Run:  python3 tools/make_logo_options.py <out-dir>
"""
import math
import os
import sys

GOLD_STOPS = (("0", "#8C6516"), ("0.28", "#E3BE62"), ("0.5", "#FFE9AE"),
              ("0.72", "#C9962C"), ("1", "#7A5612"))
SILVER_STOPS = (("0", "#6E757C"), ("0.3", "#C9D0D6"), ("0.5", "#F4F7F9"),
                ("0.74", "#9AA2A9"), ("1", "#5E656B"))
BLACK = "#0B0C0D"
INK = "#121415"


def metal(name, stops, x2="1", y2="1"):
    inner = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in stops)
    return (f'<linearGradient id="{name}" x1="0" y1="0" x2="{x2}" y2="{y2}">'
            f'{inner}</linearGradient>')


def wrap(body, defs="", size=512, bg=BLACK):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}"
     width="{size}" height="{size}" role="img">
  <defs>
    {metal('gold', GOLD_STOPS)}
    {metal('silver', SILVER_STOPS)}
    {metal('goldFlat', GOLD_STOPS, x2="0", y2="1")}
    {defs}
  </defs>
  <rect width="{size}" height="{size}" fill="{bg}"/>
  {body}
</svg>
"""


# ------------------------------------------------- 1. the seal, in metal
def seal():
    """The mark the site already has, rebuilt in gold and silver.

    Keeps what people have started to recognise and changes only the metal,
    which is the cheapest way to look more serious without starting again.
    """
    cx = cy = 256
    r = 150
    arcs = []
    for rot in (0, 90, 180, 270):
        a0, a1 = math.radians(rot + 10), math.radians(rot + 80)
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        arcs.append(f'<path d="M {x0:.1f} {y0:.1f} A {r} {r} 0 0 1 '
                    f'{x1:.1f} {y1:.1f}" fill="none" stroke="url(#silver)" '
                    f'stroke-width="34" stroke-linecap="round"/>')
    return wrap(f"""
  <circle cx="{cx}" cy="{cy}" r="212" fill="none" stroke="url(#gold)"
          stroke-width="5" opacity=".75"/>
  {''.join(arcs)}
  <circle cx="{cx}" cy="{cy}" r="62" fill="url(#gold)"/>
  <circle cx="{cx}" cy="{cy}" r="62" fill="none" stroke="{INK}"
          stroke-width="3" opacity=".35"/>""")


# ------------------------------------------- 2. the four-link chain
def chain():
    """Four links, for the four parties that sign every finished project.

    Arranged on a square with a shallow overlap rather than crowded round a
    centre. The first attempt put four big rings 74px from the middle and
    they merged into one grey blob — at 28px it was unreadable, which for a
    logo is the size that counts.
    """
    body = []
    cx, cy, r, w, d = 256, 256, 74, 26, 78
    spots = [(cx, cy - d), (cx + d, cy), (cx, cy + d), (cx - d, cy)]
    for i, (x, y) in enumerate(spots):
        colour = "url(#gold)" if i == 0 else "url(#silver)"
        body.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" '
                    f'stroke="{colour}" stroke-width="{w}"/>')
    # The student's link passes over the two it touches, so the thing reads
    # as a chain rather than as four rings that happen to be near each other.
    x, y = spots[0]
    body.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" '
                f'stroke="url(#gold)" stroke-width="{w}" '
                f'stroke-dasharray="58 407" stroke-dashoffset="-146"/>')
    return wrap("\n  ".join(body))


# --------------------------------------------- 3. the PX monogram
def monogram():
    """A letterform mark: P in silver, X in gold.

    Rebuilt with room around it. The first version crowded both letters
    against the ring and drew the P as a stem plus a stroked arc, which at
    any real size looked like a mistake rather than a letter.
    """
    return wrap(f"""
  <circle cx="256" cy="256" r="202" fill="none" stroke="url(#gold)"
          stroke-width="7"/>
  <circle cx="256" cy="256" r="182" fill="none" stroke="url(#silver)"
          stroke-width="2" opacity=".55"/>

  <!-- P, drawn as one filled shape so the bowl closes properly -->
  <path d="M 168 146
           L 168 366
           L 206 366
           L 206 286
           L 248 286
           A 70 70 0 0 0 248 146
           Z
           M 206 184
           L 246 184
           A 32 32 0 0 1 246 248
           L 206 248
           Z"
        fill="url(#silver)" fill-rule="evenodd"/>

  <!-- X, set below and right, clear of the bowl -->
  <path d="M 262 268 L 348 366" stroke="url(#gold)" stroke-width="32"
        stroke-linecap="round"/>
  <path d="M 348 268 L 262 366" stroke="url(#gold)" stroke-width="32"
        stroke-linecap="round"/>""")


# ------------------------------------------ 4. the certification stamp
def stamp():
    """A struck medallion: notched rim, raised centre.

    Leans hardest on what the product actually issues — a record somebody
    checks — and is the one that looks least like a tech logo.
    """
    notches = []
    for i in range(36):
        a = math.radians(i * 10)
        x1, y1 = 256 + 196 * math.cos(a), 256 + 196 * math.sin(a)
        x2, y2 = 256 + 214 * math.cos(a), 256 + 214 * math.sin(a)
        notches.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
                       f'y2="{y2:.1f}" stroke="url(#gold)" stroke-width="9" '
                       f'stroke-linecap="round" opacity=".9"/>')
    return wrap(f"""
  {''.join(notches)}
  <circle cx="256" cy="256" r="188" fill="none" stroke="url(#gold)" stroke-width="12"/>
  <circle cx="256" cy="256" r="162" fill="none" stroke="url(#silver)" stroke-width="4"/>
  <circle cx="256" cy="256" r="132" fill="url(#goldFlat)" opacity=".14"/>

  <!-- a check struck into the middle -->
  <path d="M 196 258 L 240 302 L 324 212" fill="none" stroke="url(#silver)"
        stroke-width="34" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 196 258 L 240 302 L 324 212" fill="none" stroke="url(#gold)"
        stroke-width="12" stroke-linecap="round" stroke-linejoin="round"
        opacity=".85"/>""")


OPTIONS = {"1-seal": seal, "2-chain": chain,
           "3-monogram": monogram, "4-stamp": stamp}

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    for name, build in OPTIONS.items():
        path = os.path.join(out, name + ".svg")
        open(path, "w").write(build())
        print(f"{name:12} {os.path.getsize(path):5,} bytes")
