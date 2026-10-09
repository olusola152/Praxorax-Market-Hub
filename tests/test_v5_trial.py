"""Free trial and imagery. Needs an EMPTY database."""
import os
from datetime import date, timedelta
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:test@127.0.0.1:5432/smv5")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false",
                  OPEN_STUDENT_SIGNUP="true", TRIAL_DAYS="7",
                  UPLOAD_FOLDER="/tmp/up5")

from app import app
from db import query, execute, scalar
app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


# ------------------------------------------------- a company signs up cold
co = app.test_client()
co.post("/register", data={"role": "company", "company_name": "Pettof Technologies",
                           "fullname": "HR Lead", "email": "hr@v5.test",
                           "password": "password123", "confirm": "password123"},
        follow_redirects=True)
with app.app_context():
    c = query("SELECT * FROM companies", one=True)
step("company starts on a trial", c["subscription_status"] == "trial",
     c["subscription_status"])
step("trial runs 7 days", c["subscribed_until"] == date.today() + timedelta(days=7),
     str(c["subscribed_until"]))
step("trial start recorded", c["trial_started_at"] is not None)

r = co.get("/company/dashboard")
step("trial company can use the app", r.status_code == 200)
step("banner counts the days down", b"Free trial" in r.data)

# a trial must not dodge the verification rule
with app.app_context():
    fid = query("SELECT id FROM fields LIMIT 1", one=True)["id"]
    sk = [str(r["id"]) for r in query("SELECT id FROM skills LIMIT 2")]
co.post("/company/projects/new", data={
    "title": "Driver earnings dashboard",
    "description": "Weekly earnings with charts and CSV export for the fleet.",
    "difficulty": "intermediate", "deadline": "2026-12-31", "max_students": "2",
    "field_id": str(fid), "skills": sk, "publish": "1"}, follow_redirects=True)
with app.app_context():
    proj = query("SELECT * FROM projects", one=True)
step("a trial still needs verification to publish", proj["status"] == "draft",
     proj["status"])

with app.app_context():
    execute("UPDATE companies SET verification_status='verified'")
co.post(f"/company/projects/{proj['id']}/publish", follow_redirects=True)
with app.app_context():
    step("verified trial company can publish",
         query("SELECT status FROM projects", one=True)["status"] == "open")

# ------------------------------------------------ a university signs up cold
un = app.test_client()
un.post("/register", data={"role": "university", "university_name": "Bells University",
                           "fullname": "Registrar", "email": "reg@v5.test",
                           "password": "password123", "confirm": "password123",
                           "city": "Ota"}, follow_redirects=True)
with app.app_context():
    u = query("SELECT * FROM universities", one=True)
step("university starts on a trial", u["subscription_status"] == "trial",
     u["subscription_status"])
step("university trial also runs 7 days",
     u["subscribed_until"] == date.today() + timedelta(days=7))
step("university can work during the trial",
     un.get("/university/dashboard").status_code == 200)
step("it can issue lecturer passcodes on the trial",
     un.get("/university/passcodes").status_code == 200)

# ------------------------------------------------------- expiry is enforced
with app.app_context():
    execute("UPDATE universities SET subscribed_until=%s",
            (date.today() - timedelta(days=1),))
r = un.get("/university/passcodes", follow_redirects=True)
step("an expired trial locks the account", b"expired" in r.data.lower())
with app.app_context():
    from workflow import expire_lapsed
    expire_lapsed()
    step("expiry is written back to the row",
         query("SELECT subscription_status FROM universities",
               one=True)["subscription_status"] == "expired")

# ------------------------------------------- an outsider needs no trial at all
st = app.test_client()
st.post("/register", data={"role": "student", "fullname": "Ada Obi",
                           "email": "ada@v5.test", "password": "password123",
                           "confirm": "password123", "field_id": str(fid)},
        follow_redirects=True)
r = st.get("/student/projects")
step("an outsider browses briefs with no trial and no subscription",
     r.status_code == 200 and b"Driver earnings" in r.data)
step("no trial banner is shown to a student", b"Free trial" not in r.data)
r = st.post(f"/student/projects/{proj['id']}/apply",
            data={"message": "I have built two Flask dashboards with Chart.js."},
            follow_redirects=True)
with app.app_context():
    step("and can apply", scalar("SELECT COUNT(*) FROM project_applications") == 1)

# ----------------------------------------------------------------- imagery
with app.app_context():
    step("field artwork is wired up",
         scalar("SELECT COUNT(*) FROM fields WHERE image_url IS NULL") == 0)
r = st.get("/student/projects")
step("feed renders cover art", b"img/fields/" in r.data)
r = st.get(f"/student/projects/{proj['id']}")
step("detail page renders a banner", r.status_code == 200 and b"detail-banner" in r.data,
     r.status_code)

pub = app.test_client()
r = pub.get("/")
step("landing page shows the hero art", b"hero-chain.svg" in r.data)
step("landing page shows faculty tiles", b"img/fields/architecture.svg" in r.data)
step("landing page sells the free week", b"free week" in r.data.lower())

print(f"\n{P} passed, {F} failed")
