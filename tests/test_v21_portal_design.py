"""The design, carried through the portal and the gate pages.

The landing page was rebuilt first and the rest of the public site was left
on the old treatment, which is worse than not having rebuilt anything: a
student who clicks through from a university portal to sign up should not
feel they have changed sites. This covers the pages that carry the design
now, and the two structural rules that make it work everywhere at once.

Run after seed_demo.py.
"""
import os

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up21",
                  TRIAL_DAYS="0", BASE_URL="https://praxorax.test")

from app import app
from db import execute, query

app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


pub = app.test_client()

with app.app_context():
    uni = query("""SELECT slug, name FROM universities
                    WHERE subscription_status IN ('active','trial')
                    ORDER BY id LIMIT 1""", one=True)

# ------------------------------------------------- the numbers band is gone
print("\n--- the counts band ---\n")

page = pub.get("/").data.decode()
step("the landing page renders", "PraxoraX" in page)
step("there is no band of live counts",
     "by the numbers" not in page and "stat-row" not in page)
step("nor the labels that went with it",
     "Briefs posted" not in page and "Institutions on board" not in page)
step("and the section it introduced is still there",
     "One chain of accountability" in page)

# ---------------------------------------------------- the portal is redesigned
print("\n--- the university portal ---\n")

if not uni:
    step("a live university exists to test against", False)
else:
    r = pub.get(f"/u/{uni['slug']}")
    page = r.data.decode()
    step("the portal renders", r.status_code == 200, r.status_code)

    step("it has the dark bar", "public-bar--dark" in page)
    step("and a dark hero", "hero-dark" in page)
    step("carrying the institution's own name at full size",
         "mega" in page and uni["name"] in page)
    step("with a picture behind it", "hero-dark__art" in page
         and ("img/photos/" in page or "img/scenes/" in page))
    step("the two ways in are given real weight",
         "join-card" in page and page.count("join-card") >= 2)
    step("a student is told they pay nothing",
         "subscription covers you" in page)
    step("a lecturer is told they need a passcode", "passcode" in page.lower())
    step("and what they leave with is shown, not just claimed",
         "feature-card" in page and "A record with" in page)
    step("the institution is named in that promise too",
         f"{uni['name']} on it" in page)

    step("nothing is left on the old pitch-row treatment",
         "pitch-num" not in page and "pitch-row" not in page)

# -------------------------------------------- the gate pages share the shell
print("\n--- sign in, register, join ---\n")

GATES = [("/login", "Sign in"), ("/register", "Create your account")]
if uni:
    GATES += [(f"/u/{uni['slug']}/login", None),
              (f"/u/{uni['slug']}/student", None),
              (f"/u/{uni['slug']}/lecturer", None)]

for path, _marker in GATES:
    r = pub.get(path)
    page = r.data.decode()
    ok = r.status_code == 200
    step(f"{path} renders", ok, r.status_code)
    if not ok:
        continue
    step(f"{path} has the photographic backdrop", 'class="gate-art"' in page)
    step(f"{path} still shows its form on paper", 'class="card"' in page
         or "panel" in page)

# The backdrop is injected from the base template for anything wearing the
# gate shell. The two pages that build their own hero must opt out, or they
# get a second photograph fixed behind the first.
print("\n--- the backdrop knows where not to go ---\n")

step("the landing page does not get a second backdrop",
     'class="gate-art"' not in pub.get("/").data.decode())
if uni:
    step("nor does a university portal front page",
         'class="gate-art"' not in pub.get(f"/u/{uni['slug']}").data.decode())
step("but a plain gate page does",
     'class="gate-art"' in pub.get("/login").data.decode())
step("and the institution finder builds its own instead of taking two",
     'class="gate-art"' not in pub.get("/join").data.decode()
     and "hero-dark" in pub.get("/join").data.decode())

# ------------------------------------------- a closed portal still explains
print("\n--- a portal that is not open ---\n")

with app.app_context():
    execute("""INSERT INTO universities (name, slug, city, admin_user_id,
                                         subscription_status, verification_status)
               SELECT 'Shut Poly', 'shut-poly', 'Ibadan', admin_user_id,
                      'expired', 'verified'
                 FROM universities WHERE slug=%s
               ON CONFLICT (slug) DO UPDATE SET subscription_status='expired'""",
            (uni["slug"],) if uni else ("",))

r = pub.get("/u/shut-poly")
page = r.data.decode()
step("a closed portal still renders", r.status_code == 200, r.status_code)
step("it says so in a card rather than an empty page", "notice-card" in page)
step("and names the real reason",
     "subscription has" in page or "not open for registration" in page)
step("it does not offer a signup button that cannot work",
     "Register as a student" not in page)
step("but staff can still get in to fix it", "sign in" in page.lower())

with app.app_context():
    execute("DELETE FROM universities WHERE slug='shut-poly'")

# ------------------------------------------------ pictures behave everywhere
print("\n--- pictures ---\n")

for path in ["/", "/login", "/register"] + ([f"/u/{uni['slug']}"] if uni else []):
    page = pub.get(path).data.decode()
    imgs = page.count("<img")
    sized = page.count('width="') >= 1
    step(f"{path} states a size for its pictures", imgs == 0 or sized,
         f"{imgs} images")


# ------------------------------- the portal does not reuse the main hero
print("\n--- a portal looks like somewhere else ---\n")

import artwork

with app.test_request_context("/"):
    ctx = {}
    for proc in app.template_context_processors[None]:
        ctx.update(proc())
    main_hero = ctx["photo_for"](ctx["hero_slot"]())

if uni:
    with app.test_request_context(f"/u/{uni['slug']}"):
        ctx = {}
        for proc in app.template_context_processors[None]:
            ctx.update(proc())
        portal_hero = ctx["photo_for"](ctx["hero_slot"]())

    step("the portal leads with a different picture to the main site",
         portal_hero != main_hero, f"{main_hero} vs {portal_hero}")

    landing = pub.get("/").data.decode()
    portal = pub.get(f"/u/{uni['slug']}").data.decode()
    step("and the two heroes are different files on the page too",
         portal_hero in portal and portal_hero not in
         landing.split('hero-dark__art')[1].split('</div>')[0],
         portal_hero)

step("every slot resolves to a file that exists",
     all(os.path.isfile(os.path.join(os.path.dirname(os.path.dirname(
         os.path.abspath(__file__))), "static", *ctx["photo_for"](s).split("/")))
         for s in artwork.SLOTS))

# Borrowing is what lets a university drop in its own photographs later.
step("a portal slot with no file of its own borrows one",
     artwork._resolve({"teamwork": "img/photos/teamwork.jpg"}, "portal-hero")
     == "img/photos/teamwork.jpg")
step("and stops borrowing the moment it has its own",
     artwork._resolve({"teamwork": "img/photos/teamwork.jpg",
                       "portal-hero": "img/photos/portal-hero.jpg"},
                      "portal-hero") == "img/photos/portal-hero.jpg")
step("a borrowing loop cannot hang the app",
     artwork._resolve({}, "portal-hero").startswith("img/"))
step("the README tells somebody how to use those slots",
     all(k in open(os.path.join(os.path.dirname(os.path.dirname(
         os.path.abspath(__file__))), "static", "img", "photos",
         "README.md")).read() for k in artwork.BORROWS_FROM))


# ------------------------------------------------------------------ the car
print("\n--- the car ---\n")

landing = pub.get("/").data.decode()
step("the car is on the landing page", "img/scenes/car.svg" in landing
     or "img/photos/car" in landing)
step("it carries the name", "PraxoraX" in open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static", "img", "scenes", "car.svg")).read())
step("and the section asks people to join",
     "Join PraxoraX" in landing or "Join {} ".format("PraxoraX") in landing)
step("it states its size like every other picture",
     'class="scene car-card' in landing or 'width="1400"' in landing,
     "car width attribute")

# The client pointed at a broker site that gives a supercar away. This one
# does not, and the copy must not imply otherwise — a promise on a real
# client's site is a promise somebody has to keep.
import re as _re
lowered = landing.lower()
for word in ("win a car", "giveaway", "prize draw", "win this"):
    step(f"the page does not promise a {word!r}", word not in lowered)

print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
