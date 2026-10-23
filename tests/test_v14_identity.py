"""The mark, the tab icon and the faculty artwork. Run after seed_demo.py.

These check the things that broke quietly while this artwork was being made,
because none of them raise an error when they go wrong:

  * a field whose tile file is missing renders a broken image, not a 500
  * a tile drawn on its own background makes the row look like six products
  * a button whose text colour matches its own background is invisible, and
    the page still returns 200
"""
import os
import re
import xml.etree.ElementTree as ET

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up14",
                  TRIAL_DAYS="0")

from app import app
from db import query

app.config["TESTING"] = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "static", "img")
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


client = app.test_client()

# ------------------------------------------------------------------ the mark
for name in ("seal.svg", "favicon.svg"):
    path = os.path.join(IMG, name)
    step(f"{name} exists", os.path.exists(path))
    if os.path.exists(path):
        try:
            ET.parse(path)
            step(f"{name} is well-formed XML", True)
        except ET.ParseError as exc:
            step(f"{name} is well-formed XML", False, str(exc))

r = client.get("/")
step("the tab icon is linked", b'rel="icon"' in r.data and b"favicon.svg" in r.data)
step("the mark is served as the header logo",
     client.get("/static/img/seal.svg").status_code == 200)
step("the tab icon is served",
     client.get("/static/img/favicon.svg").status_code == 200)

css = open(os.path.join(ROOT, "static", "css", "style.css")).read()
step("the mark is drawn from the file, not from CSS borders",
     "img/seal.svg" in css)

# The tab icon carries its own ground because a browser tab may be any colour.
favicon = open(os.path.join(IMG, "favicon.svg")).read()
step("the tab icon has an opaque plate behind it",
     "<rect" in favicon and "#1E4B3A" in favicon)

# ---------------------------------------------------------- faculty artwork
tiles = sorted(f for f in os.listdir(os.path.join(IMG, "fields"))
               if f.endswith(".svg"))
step("every faculty tile is present", len(tiles) >= 25, len(tiles))

grounds, accents, broken = set(), set(), []
for t in tiles:
    body = open(os.path.join(IMG, "fields", t)).read()
    try:
        ET.fromstring(body)
    except ET.ParseError as exc:
        broken.append(f"{t}: {exc}")
    grounds.add(tuple(re.findall(r'stop-color="(#[0-9A-Fa-f]{6})"', body)))
    accents |= set(re.findall(r'(?:stroke|fill)="(#[0-9A-Fa-f]{6})"', body))

step("every tile is well-formed XML", not broken, "; ".join(broken[:2]))
step("every tile shares one ground, so the row reads as one set",
     len(grounds) == 1, sorted(grounds)[0] if grounds else None)
step("the ground is the brand's seal green",
     grounds and all("#132A21" in g for g in grounds), sorted(grounds))
step("the accents are a small deliberate palette, not one hue per field",
     3 <= len(accents) <= 8, sorted(accents))

# A field with no artwork renders a broken image on the public feed, and
# nothing anywhere raises. This is the only place that would notice.
with app.app_context():
    fields = [f["name"] for f in query("SELECT name FROM fields")]
missing = []
for name in fields:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not os.path.exists(os.path.join(IMG, "fields", slug + ".svg")):
        missing.append(slug)
step("every field in the database has a tile", not missing, missing)

# ----------------------------------------------------------- the hero plate
hero = os.path.join(IMG, "hero-chain.svg")
try:
    ET.parse(hero)
    step("the hero artwork is well-formed XML", True)
except ET.ParseError as exc:
    step("the hero artwork is well-formed XML", False, str(exc))

hero_body = open(hero).read()
m = re.search(r'viewBox="0 0 (\d+) (\d+)"', hero_body)
step("the hero declares a viewBox", bool(m))
if m:
    page = r.data.decode()
    # Since v20 the landing hero is a scene from static/img/scenes rather
    # than hero-chain.svg, and the picture is chosen at render time — a real
    # photograph dropped into static/img/photos replaces the drawing without
    # a template edit. What this check is for is unchanged and matters more
    # now: whatever ends up in the slot must state its own size, or the page
    # lays out at zero height and everything below the hero jumps when the
    # image lands.
    import artwork
    sizes = app.config["PHOTO_SIZES"]
    step("every picture on the landing page declares its own size",
         all(f'width="{w}" height="{h}"' in page
             for slot, (w, h) in sizes.items()
             if f"/{slot}." in page),
         f"{len(sizes)} slots measured")
    step("the hero in particular", bool(sizes.get("presenting")) and
         'width="%d" height="%d"' % sizes["presenting"] in page,
         sizes.get("presenting"))
    step("and the hero is not deferred, being the first thing seen",
         'loading="eager"' in page)

step("the hero shows the certificate rather than a diagram of the software",
     "CERTIFICATE OF SUPERVISED PRACTICE" in hero_body)
step("including the serial that makes it checkable", "PX-" in hero_body)

# -------------------------------------------------- buttons must be visible
# On the green closing band the solid button inherits the band's own colour.
# The fix is a pair of rules, and the second has to restate its text colour
# or equal specificity makes the later rule win and the button disappears.
cta_rules = [m.start() for m in re.finditer(r"\.band--cta \.btn\b(?!-)", css)]
quiet_rules = [m.start() for m in re.finditer(r"\.band--cta \.btn--quiet", css)]
step("the closing band restyles its solid button", bool(cta_rules))
step("and restates the secondary button after it",
     bool(quiet_rules) and max(quiet_rules) > max(cta_rules))

band = css[max(quiet_rules):max(quiet_rules) + 240] if quiet_rules else ""
step("the secondary button sets its own text colour there",
     "color:" in band and "#F2F7F3" in band)

# ---------------------------------------------------------- every page still
pages = ["/", "/login", "/register", "/verify"]
for page in pages:
    resp = client.get(page)
    step(f"{page} renders", resp.status_code == 200, resp.status_code)
    step(f"{page} carries the mark", b"mark-seal" in resp.data)

print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
