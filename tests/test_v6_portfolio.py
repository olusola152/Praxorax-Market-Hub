"""Rename, portfolio, sharing and the consolidated certificate.
Needs an EMPTY database."""
import io, os
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:test@127.0.0.1:5432/smv6")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", OPEN_STUDENT_SIGNUP="true",
                  TRIAL_DAYS="7", UPLOAD_FOLDER="/tmp/up6")

from app import app
from db import query, execute, scalar
app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


# ------------------------------------------------------------- the rename
pub = app.test_client()
r = pub.get("/")
step("landing page carries the new name", b"PraxoraX" in r.data)
step("old name is gone", b"Client Marketplace" not in r.data)
step("title tag is clean",
     b"<title>PraxoraX \xe2\x80\x94 real projects" in r.data
     or b"PraxoraX" in r.data.split(b"</title>")[0])
step("the trial band is in the page, not the title",
     b"Try the whole thing for a week" in r.data.split(b"</title>")[1])

# ------------------------------------------------------------- a full run
co = app.test_client()
co.post("/register", data={"role": "company", "company_name": "Pettof Technologies",
                           "fullname": "HR Lead", "email": "hr@v6.test",
                           "password": "password123", "confirm": "password123"},
        follow_redirects=True)
with app.app_context():
    execute("UPDATE companies SET verification_status='verified'")
    fid = query("SELECT id FROM fields WHERE name='Software Engineering'", one=True)["id"]
    sk = [str(x["id"]) for x in query("SELECT id FROM skills LIMIT 3")]

co.post("/company/projects/new", data={
    "title": "Driver earnings dashboard",
    "description": "Weekly driver earnings with charts and CSV export.",
    "difficulty": "intermediate", "deadline": "2026-12-31", "max_students": "2",
    "field_id": str(fid), "skills": sk, "publish": "1"}, follow_redirects=True)
with app.app_context():
    proj = query("SELECT * FROM projects", one=True)

st = app.test_client()
st.post("/register", data={"role": "student", "fullname": "Ada Obi",
                           "email": "ada@v6.test", "password": "password123",
                           "confirm": "password123", "field_id": str(fid)},
        follow_redirects=True)

r = st.get("/student/portfolio")
step("empty portfolio renders", r.status_code == 200 and b"Nothing finished yet" in r.data)
r = st.post("/student/portfolio/certificate", follow_redirects=True)
step("cannot certify an empty record", b"nothing to certify" in r.data)

st.post(f"/student/projects/{proj['id']}/apply",
        data={"message": "I have built two Flask dashboards with Chart.js."},
        follow_redirects=True)
with app.app_context():
    appn = query("SELECT * FROM project_applications", one=True)
co.post(f"/company/applications/{appn['id']}/accept", follow_redirects=True)
with app.app_context():
    asg = query("SELECT * FROM assignments", one=True)

st.post(f"/student/work/{asg['id']}", data={
    "notes": "Charts and CSV export done.",
    "files": [(io.BytesIO(b"zip bytes"), "dashboard.zip")]},
    content_type="multipart/form-data", follow_redirects=True)
with app.app_context():
    sub = query("SELECT * FROM submissions", one=True)
co.post(f"/company/submissions/{sub['id']}",
        data={"action": "approve", "comment": "Good work."}, follow_redirects=True)
with app.app_context():
    step("placement completed",
         query("SELECT status FROM assignments", one=True)["status"] == "completed")

# ------------------------------------------------------------- portfolio
r = st.get("/student/portfolio")
step("completed project appears", b"Driver earnings" in r.data)
step("shows the type of work", b"Software Engineering" in r.data)
step("shows start and completion times", b"Started" in r.data and b"Completed" in r.data)
step("shows how they joined", b"Applied directly" in r.data)
step("shows submission counts", b"Versions submitted" in r.data)
step("shows the per-project certificate", b"Certificate" in r.data)

st.post("/student/portfolio/headline",
        data={"headline": "Final-year CS student — Flask and dashboards"},
        follow_redirects=True)
step("headline saved",
     b"Final-year CS student" in st.get("/student/portfolio").data)

# ---------------------------------------------------------------- sharing
step("portfolio is private by default",
     scalar("SELECT COUNT(*) FROM student_profiles WHERE portfolio_public") == 0
     if app.app_context().push() is None else False)
st.post("/student/portfolio/share", follow_redirects=True)
with app.app_context():
    token = query("SELECT portfolio_token FROM student_profiles WHERE portfolio_public",
                  one=True)["portfolio_token"]
step("public link created", bool(token))

anon = app.test_client()
r = anon.get(f"/p/{token}")
step("stranger can open the public portfolio", r.status_code == 200 and b"Ada Obi" in r.data)
step("public view hides the sharing controls", b"Make it private again" not in r.data)
step("public view hides the email", b"ada@v6.test" not in r.data)
step("a wrong token is refused", anon.get("/p/not-a-real-token").status_code == 404)

st.post("/student/portfolio/share", follow_redirects=True)
step("revoking kills the old link", anon.get(f"/p/{token}").status_code == 404)

# ------------------------------------------------------------ certificate
r = st.post("/student/portfolio/certificate", follow_redirects=True)
with app.app_context():
    cert = query("SELECT * FROM portfolio_certificates", one=True)
step("certificate issued", bool(cert) and cert["project_count"] == 1)
step("reference looks right", cert["reference"].startswith("PX-"), cert["reference"])
step("snapshot stored", bool(cert["snapshot"]))

r = anon.get(f"/certificate/{cert['reference']}")
step("certificate is publicly viewable", r.status_code == 200)
step("it names the student", b"Ada Obi" in r.data)
step("it lists the project", b"Driver earnings" in r.data)
step("it carries the brand", b"PraxoraX" in r.data)
step("it has a print control", b"window.print()" in r.data)

# the snapshot must not drift when more work lands later
with app.app_context():
    execute("UPDATE projects SET title='Renamed after the fact'")
r = anon.get(f"/certificate/{cert['reference']}")
step("certificate is frozen at issue time", b"Driver earnings" in r.data)

# ---------------------------------------------------------- verification
r = anon.post("/verify", data={"reference": cert["reference"]}, follow_redirects=True)
step("reference verifies", b"Valid" in r.data and b"Ada Obi" in r.data)
r = anon.post("/verify", data={"reference": cert["reference"].lower()},
              follow_redirects=True)
step("lowercase reference still verifies", b"Valid" in r.data)
r = anon.post("/verify", data={"reference": "PX-DEADBEEF00"}, follow_redirects=True)
step("a made-up reference is rejected", b"Not found" in r.data)

with app.app_context():
    per_project = query("SELECT certificate_number FROM certificates", one=True)
r = anon.post("/verify", data={"reference": per_project["certificate_number"]},
              follow_redirects=True)
step("per-project certificates verify too", b"Valid" in r.data)

with app.app_context():
    execute("UPDATE portfolio_certificates SET revoked_at=NOW()")
r = anon.post("/verify", data={"reference": cert["reference"]}, follow_redirects=True)
step("a revoked certificate says so", b"Revoked" in r.data)


# ------------------------------- the empty state must never be a dead button
with app.app_context():
    execute("UPDATE assignments SET status='submitted'")
r = st.get("/student/portfolio")
step("no disabled button when there is nothing to certify", b"disabled" not in r.data)
step("the empty state explains itself", b"nothing to" in r.data)
step("it shows what is still in flight", b"In progress right now" in r.data)
step("it names the stage in plain words",
     any(w in r.data for w in (b"with the company", b"with your supervisor",
                               b"with the university", b"not submitted yet",
                               b"approved", b"corrections requested")))
r = st.post("/student/portfolio/certificate", follow_redirects=True)
step("forcing the POST still explains", b"nothing to certify" in r.data)
with app.app_context():
    execute("UPDATE assignments SET status='completed'")

print(f"\n{P} passed, {F} failed")
