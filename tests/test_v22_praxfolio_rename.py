"""The portfolio became the Praxfolio.

A rename is easy to do badly: the visible word changes, a bookmark dies, a
template still says the old name, and — worst here — a link an employer was
given stops resolving. The whole promise of this feature is that somebody
outside can check a record months later, so the public links are the part
that must not move.

Run after seed_demo.py.
"""
import os
import re

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up22",
                  TRIAL_DAYS="0", BASE_URL="https://praxorax.test")

from app import app
from db import query

app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


def login(address, password="demo1234"):
    c = app.test_client()
    c.post("/login", data={"email": address, "password": password})
    return c


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ------------------------------------------------- the public links stand
print("\n--- what an employer was given still works ---\n")

pub = app.test_client()

step("the verification page is where it was",
     pub.get("/verify").status_code == 200)

with app.app_context():
    cert = query("""SELECT certificate_number FROM certificates
                     ORDER BY id LIMIT 1""", one=True)
if cert:
    r = pub.get(f"/certificate/{cert['certificate_number']}")
    step("a certificate link is where it was", r.status_code == 200,
         r.status_code)
else:
    step("a certificate exists to check", True, "none seeded — path untested")

# The shareable link is /p/<token> and always was. A rename that moved it
# would quietly break every record already handed out.
src = open(os.path.join(ROOT, "routes", "praxfolio.py")).read()
step("the shareable link is still /p/<token>", '"/p/<token>"' in src)
step("and the certificate link still /certificate/<reference>",
     '"/certificate/<reference>"' in src)
step("and verification still /verify", '"/verify"' in src)

# ------------------------------------------------- the old student URL
print("\n--- an old bookmark ---\n")

me = login("ada@demo.marketplace")
r = me.get("/student/portfolio")
step("the old student URL still answers", r.status_code in (301, 302, 308),
     r.status_code)
step("and sends them to the new one",
     "praxfolio" in r.headers.get("Location", ""), r.headers.get("Location"))
r = me.get("/student/portfolio", follow_redirects=True)
step("which renders", r.status_code == 200, r.status_code)

r = me.get("/student/praxfolio")
step("the new URL is the real one", r.status_code == 200, r.status_code)

# --------------------------------------------------- the name on screen
print("\n--- what it is called now ---\n")

page = me.get("/student/praxfolio").data.decode()
step("the page calls it a Praxfolio", "Praxfolio" in page)
step("and not a portfolio", not re.search(r"\bportfolios?\b", page, re.I),
     re.findall(r"\b[Pp]ortfolios?\b", page)[:3])

nav = me.get("/student/dashboard").data.decode()
step("so does the navigation", "Praxfolio" in nav)
step("with the old word gone from it",
     not re.search(r"\bportfolios?\b", nav, re.I),
     re.findall(r"\b[Pp]ortfolios?\b", nav)[:3])

landing = pub.get("/").data.decode()
step("the landing page uses the new name too",
     not re.search(r"\bportfolios?\b", landing, re.I),
     re.findall(r"\b[Pp]ortfolios?\b", landing)[:3])

# ------------------------------------------ no visible page says the old word
print("\n--- nowhere else either ---\n")

PAGES = ["/", "/login", "/register", "/join", "/verify"]
with app.app_context():
    uni = query("""SELECT slug FROM universities
                    WHERE subscription_status IN ('active','trial')
                    ORDER BY id LIMIT 1""", one=True)
if uni:
    PAGES.append(f"/u/{uni['slug']}")

for path in PAGES:
    body = pub.get(path).data.decode()
    hits = re.findall(r"\b[Pp]ortfolios?\b", body)
    step(f"{path} does not say the old name", not hits, hits[:3])

for path in ["/student/praxfolio", "/student/dashboard", "/student/projects"]:
    body = me.get(path).data.decode()
    hits = re.findall(r"\b[Pp]ortfolios?\b", body)
    step(f"{path} does not say the old name", not hits, hits[:3])

# ------------------------------------- the database was deliberately left
print("\n--- the schema was not dragged along ---\n")

# Renaming a column means a migration against a live database and buys
# nothing anybody can see. These names stay, and this records that it was a
# decision rather than something missed.
with app.app_context():
    cols = query("""SELECT column_name FROM information_schema.columns
                     WHERE table_name='student_profiles'""")
    names = {c["column_name"] for c in cols}
step("the token column keeps its name", "portfolio_token" in names, sorted(names)[:6])
step("and the public flag too", "portfolio_public" in names)

tabs = None
with app.app_context():
    tabs = query("""SELECT table_name FROM information_schema.tables
                     WHERE table_name='portfolio_certificates'""")
step("as does the certificates table", bool(tabs))

step("and the code still reads them under those names",
     "portfolio_token" in src and "portfolio_public" in src)

print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
