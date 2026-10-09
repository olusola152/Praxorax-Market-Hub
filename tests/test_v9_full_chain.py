"""The whole journey, start to finish, the way a person actually walks it:

    student submits -> supervisor forwards -> university forwards ->
    company approves -> placement completed -> portfolio fills ->
    certificate generated -> certificate verifies

Plus what the student sees at every stage while waiting.
Run after seed_demo.py.
"""
import io, os
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up9")

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
    execute("UPDATE companies SET subscription_status='active', "
            "verification_status='verified'")
    asg = query("""SELECT a.id, a.student_id, a.project_id, u.email AS student_email,
                          u.fullname AS student_name, p.title,
                          lu.email AS lecturer_email,
                          cu.email AS company_email,
                          uu.email AS registrar_email
                     FROM assignments a
                     JOIN users u  ON u.id  = a.student_id
                     JOIN users lu ON lu.id = a.lecturer_id
                     JOIN projects p ON p.id = a.project_id
                     JOIN companies c ON c.id = p.company_id
                     JOIN users cu ON cu.id = c.user_id
                     JOIN lecturer_profiles lp ON lp.user_id = a.lecturer_id
                     JOIN universities un ON un.id = lp.university_id
                     JOIN users uu ON uu.id = un.admin_user_id
                    WHERE a.lecturer_id IS NOT NULL
                      AND a.status NOT IN ('completed','cancelled') LIMIT 1""", one=True)
    # a clean placement to walk
    execute("DELETE FROM submissions WHERE assignment_id=%s", (asg["id"],))
    execute("UPDATE assignments SET status='assigned', completed_at=NULL WHERE id=%s", (asg["id"],))
    execute("DELETE FROM certificates WHERE student_id=%s AND project_id=%s",
            (asg["student_id"], asg["project_id"]))
    execute("DELETE FROM portfolio_certificates WHERE student_id=%s",
            (asg["student_id"],))

st = login(asg["student_email"])
lc = login(asg["lecturer_email"])
un = login(asg["registrar_email"])
co = login(asg["company_email"])

# ------------------------------------------------------- 1. student submits
r = st.get(f"/student/work/{asg['id']}")
step("form is available before submitting", b"Submit version 1" in r.data)

r = st.post(f"/student/work/{asg['id']}", data={
    "notes": "Everything: source, tests and the guide.",
    "files": [(io.BytesIO(b"PK zip bytes"), "project.zip"),
              (io.BytesIO(b"%PDF guide"), "guide.pdf")]},
    content_type="multipart/form-data", follow_redirects=True)
with app.app_context():
    sub = query("SELECT * FROM submissions WHERE assignment_id=%s", (asg["id"],), one=True)
    files = query("SELECT * FROM submission_files WHERE submission_id=%s", (sub["id"],))
step("whole project sent in one go", sub and len(files) == 2, len(files))
step("it is with the supervisor", sub["stage"] == "with_lecturer", sub["stage"])

# ------------------------------------ what the student sees while waiting
r = st.get(f"/student/work/{asg['id']}")
step("submit form is replaced while under review", b"Submit version 2" not in r.data)
step("the page says where it is", b"with your supervisor" in r.data)
step("it shows the chain", b"chain-step" in r.data)

r = st.post(f"/student/work/{asg['id']}", data={"notes": "again"},
            content_type="multipart/form-data", follow_redirects=True)
step("forcing a second submission is explained, not just refused",
     b"with your supervisor" in r.data and b"once they respond" in r.data)

# ------------------------------------------------ 2. supervisor forwards
r = lc.get(f"/lecturer/submissions/{sub['id']}")
step("supervisor can open it", r.status_code == 200 and b"project.zip" in r.data)
r = lc.post(f"/lecturer/submissions/{sub['id']}",
            data={"action": "forward", "comment": "Checked and correct."},
            follow_redirects=True)
with app.app_context():
    sub = query("SELECT * FROM submissions WHERE id=%s", (sub["id"],), one=True)
step("forwarded to the university", sub["stage"] == "with_university", sub["stage"])

r = st.get(f"/student/work/{asg['id']}")
step("student now told it is with the university", b"with the university" in r.data)
step("still no submit form", b"Submit version 2" not in r.data)

# ------------------------------------------------ 3. university forwards
r = un.get(f"/university/submissions/{sub['id']}")
step("university can open it", r.status_code == 200)
r = un.post(f"/university/submissions/{sub['id']}",
            data={"action": "forward", "comment": "Passed on."}, follow_redirects=True)
with app.app_context():
    sub = query("SELECT * FROM submissions WHERE id=%s", (sub["id"],), one=True)
step("forwarded to the company", sub["stage"] == "with_company", sub["stage"])

r = st.get(f"/student/work/{asg['id']}")
step("student told it is with the company", b"with the company" in r.data)

# --------------------------------------------------- 4. company approves
r = co.get(f"/company/submissions/{sub['id']}")
step("company can open it", r.status_code == 200 and b"guide.pdf" in r.data)
r = co.post(f"/company/submissions/{sub['id']}",
            data={"action": "approve", "comment": "Accepted, thank you."},
            follow_redirects=True)
with app.app_context():
    sub = query("SELECT * FROM submissions WHERE id=%s", (sub["id"],), one=True)
    placement = query("SELECT * FROM assignments WHERE id=%s", (asg["id"],), one=True)
    cert = query("""SELECT * FROM certificates WHERE student_id=%s AND project_id=%s""",
                 (asg["student_id"], asg["project_id"]), one=True)
step("submission approved", sub["stage"] == "approved", sub["stage"])
step("placement marked completed", placement["status"] == "completed",
     placement["status"])
step("completion time recorded", placement["completed_at"] is not None)
step("per-project certificate issued", bool(cert))

# ------------------------------------------------------- 5. the portfolio
r = st.get("/student/portfolio")
step("completed work is in the portfolio", asg["title"].encode() in r.data)
step("the certificate button is there now", b"Generate a certificate" in r.data)
step("the empty-state message is gone", b"nothing to\n      certify" not in r.data)

r = st.post("/student/portfolio/certificate", follow_redirects=True)
with app.app_context():
    pc = query("""SELECT * FROM portfolio_certificates WHERE student_id=%s
                   ORDER BY id DESC LIMIT 1""", (asg["student_id"],), one=True)
step("consolidated certificate generated", bool(pc))
step("it covers the project", pc["project_count"] >= 1, pc["project_count"])
step("the certificate page opens", b"Record of completed project work" in r.data)
step("it names the student", asg["student_name"].encode() in r.data)

# --------------------------------------------------------- 6. verification
anon = app.test_client()
r = anon.post("/verify", data={"reference": pc["reference"]}, follow_redirects=True)
step("anyone can verify it", b"Valid" in r.data and asg["student_name"].encode() in r.data)
r = anon.post("/verify", data={"reference": cert["certificate_number"]},
              follow_redirects=True)
step("the per-project one verifies too", b"Valid" in r.data)

# ------------------------------- 7. and the student can submit again after
with app.app_context():
    other = query("""SELECT a.id, u.email FROM assignments a
                       JOIN users u ON u.id = a.student_id
                      WHERE a.id <> %s AND a.lecturer_id IS NOT NULL
                        AND a.status NOT IN ('completed','cancelled') LIMIT 1""",
                  (asg["id"],), one=True)
if other:
    st2 = login(other["email"])
    r = st2.get(f"/student/work/{other['id']}")
    step("a different placement is unaffected", r.status_code == 200)

# revision reopens the form
with app.app_context():
    third = query("""SELECT a.id, a.student_id, u.email, lu.email AS lecturer_email
                       FROM assignments a JOIN users u ON u.id=a.student_id
                       JOIN users lu ON lu.id=a.lecturer_id
                      WHERE a.lecturer_id IS NOT NULL
                        AND a.status NOT IN ('completed','cancelled')
                        AND a.id <> %s LIMIT 1""", (asg["id"],), one=True)
if third:
    s3 = login(third["email"])
    with app.app_context():
        execute("DELETE FROM submissions WHERE assignment_id=%s", (third["id"],))
    s3.post(f"/student/work/{third['id']}", data={
        "notes": "First go.", "files": [(io.BytesIO(b"x"), "a.pdf")]},
        content_type="multipart/form-data", follow_redirects=True)
    with app.app_context():
        s3sub = query("SELECT * FROM submissions WHERE assignment_id=%s",
                      (third["id"],), one=True)
    l3 = login(third["lecturer_email"])
    l3.post(f"/lecturer/submissions/{s3sub['id']}",
            data={"action": "request_correction",
                  "comment": "The CSV export is missing entirely."},
            follow_redirects=True)
    r = s3.get(f"/student/work/{third['id']}")
    step("corrections reopen the submit form", b"Submit version 2" in r.data)

print(f"\n{P} passed, {F} failed")
