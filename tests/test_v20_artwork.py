"""The drop-in picture system.

Every illustrated slot on the public site can be replaced by a real
photograph by copying a file into static/img/photos with the right name.
No template is edited and no code is deployed. That is a claim made in a
README somebody will follow months from now, so it is worth proving.

Needs no database.
"""
import os
import shutil
import tempfile

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up20t")

import artwork

P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(HERE, "static")

# -------------------------------------------------- the slots are described
print("\n--- the slots ---\n")

step("every slot has a description for somebody who cannot see it",
     all(len(v) > 30 for v in artwork.SLOTS.values()))
# Since v21 a slot either owns a drawing or borrows another slot's picture.
# Only the first kind needs a file of its own; a borrower that also had one
# would be a drawing nothing ever shows.
OWNS = [s for s in artwork.SLOTS if s not in artwork.BORROWS_FROM]
step("the drawings exist for every slot that owns one",
     all(os.path.isfile(os.path.join(STATIC, "img", "scenes", s + ".svg"))
         for s in OWNS),
     [s for s in OWNS
      if not os.path.isfile(os.path.join(STATIC, "img", "scenes", s + ".svg"))])
step("and a borrowing slot points at a slot that exists",
     all(v in artwork.SLOTS for v in artwork.BORROWS_FROM.values()),
     [v for v in artwork.BORROWS_FROM.values() if v not in artwork.SLOTS])
step("no slot borrows from itself",
     all(k != v for k, v in artwork.BORROWS_FROM.items()))
step("the photos folder exists to be dropped into",
     os.path.isdir(os.path.join(STATIC, "img", "photos")))
step("and explains itself to whoever opens it",
     os.path.isfile(os.path.join(STATIC, "img", "photos", "README.md")))

readme = open(os.path.join(STATIC, "img", "photos", "README.md")).read()
step("the README names every slot, so none is a secret",
     all(s in readme for s in artwork.SLOTS),
     [s for s in artwork.SLOTS if s not in readme])

# ------------------------------------------------------ measuring a drawing
print("\n--- measuring ---\n")

scene = os.path.join(STATIC, "img", "scenes", "presenting.svg")
size = artwork._measure(scene)
step("an SVG is measured from its viewBox", size is not None, size)
step("and the numbers are sane", size and size[0] > 200 and size[1] > 200, size)
step("a file that is not there measures as nothing",
     artwork._measure(os.path.join(STATIC, "img", "scenes", "nope.svg")) is None)

# --------------------------------------------- the fallback and the override
print("\n--- dropping a photograph in ---\n")

work = tempfile.mkdtemp()
os.makedirs(os.path.join(work, "img", "photos"))
os.makedirs(os.path.join(work, "img", "scenes"))
for s in OWNS:
    shutil.copy(os.path.join(STATIC, "img", "scenes", s + ".svg"),
                os.path.join(work, "img", "scenes", s + ".svg"))

found = artwork._scan(work)
step("with an empty folder, nothing claims to be a photograph", found == {}, found)

# A real JPEG, so the measuring path is the one that runs in production.
from PIL import Image
Image.new("RGB", (1920, 1080), "#345").save(
    os.path.join(work, "img", "photos", "presenting.jpg"), "JPEG")

found = artwork._scan(work)
step("a dropped file is picked up", found.get("presenting") == "img/photos/presenting.jpg",
     found)
step("and only for its own slot", set(found) == {"presenting"}, set(found))

step("a photograph is measured too",
     artwork._measure(os.path.join(work, "img", "photos", "presenting.jpg"))
     == (1920, 1080))

# Format precedence: a modern format beside a jpg should win, because
# somebody who made one did it to save bytes.
Image.new("RGB", (1920, 1080), "#345").save(
    os.path.join(work, "img", "photos", "presenting.webp"), "WEBP")
found = artwork._scan(work)
step("webp beats jpg when both are there",
     found["presenting"].endswith(".webp"), found["presenting"])

# A name that is not a slot must be ignored rather than guessed at.
Image.new("RGB", (10, 10), "#345").save(
    os.path.join(work, "img", "photos", "hero.jpg"), "JPEG")
found = artwork._scan(work)
step("a file named something else is ignored",
     "hero" not in found and set(found) == {"presenting"}, set(found))

# ------------------------------------------------- wired into a live app
print("\n--- through the app ---\n")

from app import app

with app.test_request_context("/"):
    ctx = {}
    for proc in app.template_context_processors[None]:
        ctx.update(proc())

    step("the templates get photo_for", callable(ctx.get("photo_for")))
    step("and photo_size", callable(ctx.get("photo_size")))
    step("and is_photo", callable(ctx.get("is_photo")))

    for slot in artwork.SLOTS:
        path = ctx["photo_for"](slot)
        real = os.path.join(STATIC, *path.split("/"))
        if not os.path.isfile(real):
            step(f"{slot} resolves to a file that exists", False, path)
            break
    else:
        step("every slot resolves to a file that exists", True)

    step("every slot has a measured size",
         all(ctx["photo_size"](s) for s in artwork.SLOTS),
         [s for s in artwork.SLOTS if not ctx["photo_size"](s)])

    step("a slot with no photograph of its own falls back",
         all(ctx["photo_for"](s).startswith(("img/scenes/", "img/photos/"))
             for s in artwork.SLOTS if not ctx["is_photo"](s)))
    step("a slot that owns its art and has no photo shows the drawing",
         all(ctx["photo_for"](s) == f"img/scenes/{s}.svg"
             for s in OWNS if not ctx["is_photo"](s)))
    step("and a slot with one uses it",
         all(ctx["photo_for"](s).startswith("img/photos/")
             for s in artwork.SLOTS if ctx["is_photo"](s)))

    step("an unknown slot still returns something rather than breaking",
         ctx["photo_for"]("not-a-slot") == "img/scenes/not-a-slot.svg")
    step("and claims no alt text it does not have",
         ctx["photo_alt"]("not-a-slot") == "")

# --------------------------------------------------- the page uses them
print("\n--- on the page ---\n")

app.config["TESTING"] = True
client = app.test_client()
page = client.get("/").data.decode()

step("the landing page renders", "PraxoraX" in page)

# Slots are not all used in the same place: a portal-only slot never appears
# on the main site and should not be expected to. Each is checked against the
# page that actually uses it.
with app.app_context():
    from db import query
    _uni = query("""SELECT slug FROM universities
                     WHERE subscription_status IN ('active','trial')
                     ORDER BY id LIMIT 1""", one=True)

PAGES = {"/": page}
if _uni:
    PAGES[f"/u/{_uni['slug']}"] = client.get(f"/u/{_uni['slug']}").data.decode()

for slot in artwork.SLOTS:
    with app.test_request_context("/"):
        ctxp = {}
        for proc in app.template_context_processors[None]:
            ctxp.update(proc())
        src = ctxp["photo_for"](slot)
    where = [p for p, body in PAGES.items() if src in body]
    step(f"the {slot} slot is shown somewhere", bool(where),
         f"{src} -> {where or 'nowhere'}")

step("the portal slots are the ones used on a portal",
     not _uni or all(
         ctxp["photo_for"](s) in PAGES[f"/u/{_uni['slug']}"]
         for s in ("portal-hero", "alerts-portal")))

step("the hero is not lazy-loaded, being the first thing anyone sees",
     'loading="eager"' in page)
step("everything else is",
     page.count('loading="lazy"') >= 3, page.count('loading="lazy"'))

shutil.rmtree(work, ignore_errors=True)
print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
