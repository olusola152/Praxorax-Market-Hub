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
# Since v11 a student needs a profile a company can judge before applying.
st.post("/student/profile", data={"bio": "Final year student. I build Flask dashboards with Chart.js and have shipped reporting tools for two small businesses.", "level": "400"},
        follow_redirects=True)
with app.app_context():
    _sk = query("SELECT id FROM skills LIMIT 1", one=True)["id"]
st.post("/student/skills", data={"skills": [str(_sk)]}, follow_redirects=True)

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
# Since v20 the hero is a scene that a real photograph can replace in place,
# so the check is that the hero slot rendered something, not that one
# particular file is hardcoded into the page.
step("landing page shows the hero art",
     b"img/scenes/presenting.svg" in r.data or b"img/photos/presenting" in r.data)
step("landing page shows faculty tiles", b"img/fields/architecture.svg" in r.data)
step("landing page sells the free week", b"free week" in r.data.lower())

# ------------------------------------------------- trials switched off
# TRIAL_DAYS=0 has to remove the offer as well as the grant. A site that
# advertises a free week and then hands out a pending account is worse than
# one that never mentioned a trial.
app.config["TRIAL_DAYS"] = 0

r = pub.get("/")
copy = r.data.lower()
step("with trials off, the landing page stops selling a free week",
     b"free week" not in copy and b"free trial" not in copy
     and b"free for 7 days" not in copy)
step("and still gives institutions a way in",
     b"register your organisation" in copy)
step("students are still told they never pay", b"never pay" in copy)

off = app.test_client()
r = off.post("/register", data={"role": "company", "fullname": "No Trial Ltd",
                                "email": "notrial@v5.test", "password": "password123",
                                "confirm": "password123",
                                "company_name": "No Trial Ltd"},
             follow_redirects=True)
step("a company can still sign up", r.status_code == 200, r.status_code)
with app.app_context():
    row = query("""SELECT subscription_status, subscribed_until
                     FROM companies WHERE name='No Trial Ltd'""", one=True)
step("but it lands on pending, not trial",
     row and row["subscription_status"] == "pending", row)
step("with no free period attached", row and row["subscribed_until"] is None)
step("and is told an administrator activates it",
     b"administrator activates your subscription" in r.data)
step("no trial countdown is shown to it", b"trial-bar" not in r.data)

with app.app_context():
    import mailer
    # The welcome copy never promises a trial; the sentence about one is
    # added only when a trial is actually on.
    step("the welcome copy makes no promise about a trial",
         all("trial" not in body for body in mailer.WELCOME.values()))
    step("and there is a sentence ready for when there is one",
         "trial" in mailer.TRIAL_SENTENCE["company"])
    step("it names the platform from the configured brand",
         "{brand}" in mailer.WELCOME["company"])

# Switching the setting off must not reach back and cut short a trial that
# was already promised.
with app.app_context():
    # The university in this suite was expired on purpose further up, to
    # prove expiry works, so the surviving trial is the company's.
    still = query("""SELECT name, subscribed_until FROM companies
                      WHERE subscription_status='trial'
                      UNION ALL
                     SELECT name, subscribed_until FROM universities
                      WHERE subscription_status='trial'""")
step("trials already running are left alone", len(still) > 0,
     [r["name"] for r in still])
step("and keep the end date they were promised",
     all(r["subscribed_until"] is not None for r in still))

r = co.get("/company/dashboard")
step("that account still sees its countdown with trials switched off",
     b"trial-bar" in r.data, r.status_code)

app.config["TRIAL_DAYS"] = 7
r = pub.get("/")
step("turning it back on restores the offer",
     b"free week" in r.data.lower())

print(f"\n{P} passed, {F} failed")
