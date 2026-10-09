"""Phase sign-off from the review page, and the alerts it sends.
Run after seed_demo.py."""
import io, os
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up7")

from app import app
from db import query, execute, scalar
app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


def login(email, pw="demo1234"):
    c = app.test_client()
    c.post("/login", data={"email": email, "password": pw})
    return c


with app.app_context():
    execute("UPDATE universities SET subscription_status='active'")
    execute("UPDATE companies SET subscription_status='active', verification_status='verified'")
    asg = query("""SELECT a.id, a.student_id, u.email
                     FROM assignments a JOIN users u ON u.id = a.student_id
                    WHERE a.lecturer_id IS NOT NULL
                      AND a.status NOT IN ('completed','cancelled') LIMIT 1""", one=True)
    execute("DELETE FROM submissions WHERE assignment_id=%s", (asg["id"],))
    execute("UPDATE milestones SET status='pending', signed_off_by=NULL, "
            "signed_off_at=NULL WHERE assignment_id=%s", (asg["id"],))
    before_alerts = scalar("SELECT COUNT(*) FROM notifications WHERE user_id=%s",
                           (asg["student_id"],))
    phases = query("SELECT * FROM milestones WHERE assignment_id=%s ORDER BY phase",
                   (asg["id"],))

st = login(asg["email"])
st.post(f"/student/work/{asg['id']}", data={
    "notes": "Phase 1 done — requirements and the ERD.",
    "files": [(io.BytesIO(b"erd bytes"), "requirements.pdf")]},
    content_type="multipart/form-data", follow_redirects=True)
with app.app_context():
    sub = query("SELECT * FROM submissions WHERE assignment_id=%s", (asg["id"],), one=True)
step("submission is with the lecturer", sub["stage"] == "with_lecturer", sub["stage"])

lc = login("bello@demo.marketplace")
r = lc.get(f"/lecturer/submissions/{sub['id']}")
step("review page offers a sign-off", r.status_code == 200 and b"Sign off a phase" in r.data)
step("it lists the phases", phases[0]["title"].encode() in r.data)
step("the button says what it does", b"no corrections needed" in r.data)

# choosing nothing is refused rather than guessed at
r = lc.post(f"/lecturer/submissions/{sub['id']}",
            data={"action": "satisfied", "milestone_id": ""}, follow_redirects=True)
step("a missing phase is refused", b"Choose which phase" in r.data)

r = lc.post(f"/lecturer/submissions/{sub['id']}", data={
    "action": "satisfied", "milestone_id": str(phases[0]["id"]),
    "comment": "Requirements are complete and the ERD is correct."},
    follow_redirects=True)
with app.app_context():
    m = query("SELECT * FROM milestones WHERE id=%s", (phases[0]["id"],), one=True)
step("phase marked done", m["status"] == "done", m["status"])
step("signer recorded", m["signed_off_by"] is not None)
step("time recorded", m["signed_off_at"] is not None)
step("note kept", "ERD is correct" in (m["note"] or ""))

with app.app_context():
    alerts = query("""SELECT * FROM notifications WHERE user_id=%s
                       ORDER BY id DESC LIMIT 1""", (asg["student_id"],), one=True)
step("student alerted", alerts and "satisfied" in alerts["body"], 
     alerts["body"][:60] if alerts else "none")
step("alert names the phase", phases[0]["title"] in alerts["body"])
step("alert carries the note", "ERD is correct" in alerts["body"])

with app.app_context():
    sub2 = query("SELECT stage FROM submissions WHERE id=%s", (sub["id"],), one=True)
step("signing off a phase does not move the submission",
     sub2["stage"] == "with_lecturer", sub2["stage"])

with app.app_context():
    rev = query("""SELECT * FROM reviews WHERE submission_id=%s
                    AND action='phase_satisfied'""", (sub["id"],), one=True)
step("decision is in the trail", bool(rev))
step("trail knows which phase", rev["milestone_id"] == phases[0]["id"])

# what the student sees
r = st.get(f"/student/work/{asg['id']}")
step("student's page states the sign-off", b"Signed off by" in r.data)
step("it names the supervisor", b"Bello" in r.data)
step("it says no corrections needed", b"no corrections needed" in r.data)

r = st.get("/student/notifications")
step("the alert is in their list", b"satisfied" in r.data)

# the monitor page alerts too
r = lc.post(f"/lecturer/milestones/{phases[1]['id']}",
            data={"status": "in_progress", "note": "Started the build."},
            follow_redirects=True)
step("monitor page says the student was told", b"student has been notified" in r.data)
with app.app_context():
    latest = query("""SELECT body FROM notifications WHERE user_id=%s
                       ORDER BY id DESC LIMIT 1""", (asg["student_id"],), one=True)
step("in-progress change alerts the student", "in progress" in latest["body"],
     latest["body"][:60])

# a lecturer cannot sign off someone else's placement
other = login("ngozi@demo.marketplace")
r = other.post(f"/lecturer/submissions/{sub['id']}", data={
    "action": "satisfied", "milestone_id": str(phases[2]["id"])})
step("another lecturer is refused", r.status_code == 404, r.status_code)

# forwarding still works afterwards
r = lc.post(f"/lecturer/submissions/{sub['id']}",
            data={"action": "forward", "comment": "All good, passing it up."},
            follow_redirects=True)
with app.app_context():
    step("forwarding still works",
         query("SELECT stage FROM submissions WHERE id=%s", (sub["id"],),
               one=True)["stage"] == "with_university")

print(f"\n{P} passed, {F} failed")
