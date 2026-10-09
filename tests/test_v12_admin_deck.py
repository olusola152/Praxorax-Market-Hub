"""The admin deck and the public students view. Run after seed_demo.py."""
import os
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up12")

from werkzeug.security import generate_password_hash
from app import app
from db import query, execute, scalar
app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


with app.app_context():
    execute("""INSERT INTO users (fullname, email, password, role)
               VALUES ('Root','root@deck.test',%s,'admin')
               ON CONFLICT (email) DO NOTHING""",
            (generate_password_hash("password123"),))
    fid = query("SELECT id FROM fields LIMIT 1", one=True)["id"]

ad = app.test_client()
ad.post("/login", data={"email": "root@deck.test", "password": "password123"})

# ------------------------------------------------------------ every page
pages = {
    "/admin/dashboard": b"Operations deck",
    "/admin/public-students": b"Public students",
    "/admin/users": b"rail-link",
    "/admin/kyc": b"rail-link",
    "/admin/companies": b"rail-link",
    "/admin/universities": b"rail-link",
    "/admin/projects": b"rail-link",
    "/admin/placements": b"rail-link",
    "/admin/subscriptions": b"rail-link",
    "/admin/activity": b"rail-link",
}
for page, needle in pages.items():
    r = ad.get(page)
    step(f"{page} renders on the deck", r.status_code == 200 and needle in r.data,
         r.status_code)

# ---------------------------------------------------------- the deck itself
r = ad.get("/admin/dashboard")
step("the chain board is the first thing shown", b"review chain" in r.data)
step("every stage of the chain is listed",
     all(w in r.data for w in (b"With supervisors", b"With universities",
                               b"With companies")))
step("signups are charted", b"spark-line" in r.data and b"polyline" in r.data)
step("the rail marks where you are", b"rail-link--on" in r.data)
step("public students are reachable from the deck",
     b"/admin/public-students" in r.data)

# the deck must be visually distinct from the rest of the app
step("admin uses the dark shell", b'class="deck"' in r.data)
st_pages = ad.get("/admin/users")
step("so does every other admin page", b'class="deck"' in st_pages.data)

# --------------------------------------------- public students, with data
pub = app.test_client()
pub.post("/register", data={"role": "student", "fullname": "Independent One",
                            "email": "indie1@deck.test", "password": "password123",
                            "confirm": "password123", "field_id": str(fid)},
         follow_redirects=True)
pub2 = app.test_client()
pub2.post("/register", data={"role": "student", "fullname": "Independent Two",
                             "email": "indie2@deck.test", "password": "password123",
                             "confirm": "password123", "field_id": str(fid)},
          follow_redirects=True)

r = ad.get("/admin/public-students")
step("a new public student appears", b"Independent One" in r.data)
step("institutional students stay out", b"ada@demo.marketplace" not in r.data)

with app.app_context():
    counted = scalar("""SELECT COUNT(*) FROM student_profiles
                         WHERE university_id IS NULL""")
step("the count matches the database", str(counted).encode() in r.data, counted)

# one of them applies, so the states separate
with app.app_context():
    execute("UPDATE companies SET subscription_status='active', "
            "verification_status='verified'")
    proj = query("SELECT id FROM projects WHERE status='open' LIMIT 1", one=True)
if proj:
    pub.post(f"/student/projects/{proj['id']}/apply",
             data={"message": "I have built two dashboards and can start immediately."},
             follow_redirects=True)

    r = ad.get("/admin/public-students?state=waiting")
    step("the waiting filter finds the applicant", b"Independent One" in r.data)
    step("and excludes the one who has not applied",
         b"Independent Two" not in r.data)

    r = ad.get("/admin/public-students?state=idle")
    step("the idle filter is the mirror image",
         b"Independent Two" in r.data and b"Independent One" not in r.data)

r = ad.get("/admin/public-students?q=Independent+Two")
step("search narrows by name",
     b"Independent Two" in r.data and b"Independent One" not in r.data)
r = ad.get("/admin/public-students?q=nobodyhere")
step("a search with no match says so", b"No public student matches" in r.data)

# --------------------------------------------------------------- access
for email, role in [("ada@demo.marketplace", "student"),
                    ("bello@demo.marketplace", "lecturer"),
                    ("hr@demo.marketplace", "company")]:
    c = app.test_client()
    c.post("/login", data={"email": email, "password": "demo1234"})
    r = c.get("/admin/public-students", follow_redirects=False)
    step(f"a {role} cannot open it", r.status_code in (302, 403), r.status_code)

anon = app.test_client()
step("a signed-out visitor is sent to sign in",
     anon.get("/admin/dashboard").status_code == 302)

print(f"\n{P} passed, {F} failed")
