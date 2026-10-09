"""Teams, deliverables, KYC and bookmarks/matching. Needs an EMPTY database."""
import io, os
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:test@127.0.0.1:5432/smv4")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false",
                  OPEN_STUDENT_SIGNUP="true", UPLOAD_FOLDER="/tmp/up4")

from app import app
from db import query, execute, scalar
app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


def student(name, email, skills=()):
    c = app.test_client()
    c.post("/register", data={"role": "student", "fullname": name, "email": email,
                              "password": "password123", "confirm": "password123",
                              "field_id": str(FID)}, follow_redirects=True)
    if skills:
        c.post("/student/skills", data={"skills": [str(s) for s in skills]},
               follow_redirects=True)
    return c


with app.app_context():
    FID = query("SELECT id FROM fields WHERE name='Software Engineering'", one=True)["id"]
    SKILLS = query("SELECT id, name FROM skills ORDER BY id LIMIT 6")
SK = [s["id"] for s in SKILLS]

# ---------------------------------------------------------------- 3. KYC
co = app.test_client()
co.post("/register", data={"role": "company", "company_name": "Pettof Technologies",
                           "fullname": "HR Lead", "email": "hr@v4.test",
                           "password": "password123", "confirm": "password123"},
        follow_redirects=True)
with app.app_context():
    execute("UPDATE companies SET subscription_status='active'")
    # migration backfills pre-existing rows; a brand-new signup must start pending
    execute("UPDATE companies SET verification_status='pending', kyc_decided_at=NULL")

r = co.post("/company/projects/new", data={
    "title": "Driver earnings dashboard",
    "description": "Weekly driver earnings with charts and CSV export for our fleet.",
    "difficulty": "intermediate", "deadline": "2026-12-31", "max_students": "3",
    "field_id": str(FID), "deliverables": "Source and a guide",
    "skills": [str(SK[0]), str(SK[1]), str(SK[2])], "publish": "1"},
    follow_redirects=True)
with app.app_context():
    proj = query("SELECT * FROM projects", one=True)
step("unverified company cannot publish", proj["status"] == "draft", proj["status"])

r = co.post("/company/verification",
            data={"kyc_document_url": "https://drive.example.com/cac.pdf"},
            follow_redirects=True)
with app.app_context():
    c = query("SELECT * FROM companies", one=True)
step("KYC document submitted", c["kyc_document_url"] and c["verification_status"] == "pending")

ad = app.test_client()
with app.app_context():
    from werkzeug.security import generate_password_hash
    execute("""INSERT INTO users (fullname, email, password, role)
               VALUES ('Root','root@v4.test',%s,'admin')""",
            (generate_password_hash("password123"),))
ad.post("/login", data={"email": "root@v4.test", "password": "password123"},
        follow_redirects=True)
step("admin sees the KYC queue", b"Pettof" in ad.get("/admin/kyc").data)

r = ad.post(f"/admin/kyc/{c['id']}/reject", data={"notes": "x"}, follow_redirects=True)
with app.app_context():
    step("reject without a real reason is refused",
         query("SELECT verification_status FROM companies", one=True)["verification_status"] == "pending")

ad.post(f"/admin/kyc/{c['id']}/verify", follow_redirects=True)
with app.app_context():
    step("admin verifies the company",
         query("SELECT verification_status FROM companies", one=True)["verification_status"] == "verified")

co.post(f"/company/projects/{proj['id']}/publish", follow_redirects=True)
with app.app_context():
    proj = query("SELECT * FROM projects", one=True)
step("verified company can now publish", proj["status"] == "open", proj["status"])

# ------------------------------------------------- 4. bookmarks + matching
ada = student("Ada Obi", "ada@v4.test", skills=SK[:3])      # all three required
kem = student("Kemi Ade", "kemi@v4.test", skills=SK[3:6])   # none of them
led = student("Tunde Bello", "tunde@v4.test", skills=SK[:2])

with app.app_context():
    step("skills saved", scalar("SELECT COUNT(*) FROM student_skills WHERE user_id="
                                "(SELECT id FROM users WHERE email='ada@v4.test')") == 3)

r = ada.get("/student/projects")
step("full-overlap student sees a strong match", b"strong match" in r.data)
r = kem.get("/student/projects")
step("no-overlap student sees no match label",
     b"match against your skills" not in r.data)

ada.post(f"/student/projects/{proj['id']}/bookmark", follow_redirects=True)
with app.app_context():
    step("brief bookmarked", scalar("SELECT COUNT(*) FROM bookmarks") == 1)
step("saved page lists it", b"Driver earnings" in ada.get("/student/bookmarks").data)
ada.post(f"/student/projects/{proj['id']}/bookmark", follow_redirects=True)
with app.app_context():
    step("bookmark toggles off", scalar("SELECT COUNT(*) FROM bookmarks") == 0)

# ------------------------------------------------------------- 1. teams
r = led.post("/teams/new", data={"name": "Night Shift"}, follow_redirects=True)
with app.app_context():
    team = query("SELECT * FROM teams", one=True)
step("team created with its maker as lead", bool(team))
with app.app_context():
    step("lead membership is active", scalar(
        "SELECT COUNT(*) FROM team_members WHERE team_id=%s AND role='lead' "
        "AND status='active'", (team["id"],)) == 1)

r = led.post(f"/teams/{team['id']}/invite", data={"email": "nobody@v4.test"},
             follow_redirects=True)
step("inviting a non-account is refused", "No account here".encode() in r.data)
r = led.post(f"/teams/{team['id']}/invite", data={"email": "hr@v4.test"},
             follow_redirects=True)
step("inviting a company is refused", b"Only students can join" in r.data)

led.post(f"/teams/{team['id']}/invite", data={"email": "ada@v4.test"},
         follow_redirects=True)
led.post(f"/teams/{team['id']}/invite", data={"email": "kemi@v4.test"},
         follow_redirects=True)
with app.app_context():
    step("two invitations sent", scalar(
        "SELECT COUNT(*) FROM team_members WHERE status='invited'") == 2)

r = ada.get("/teams/")
step("invitee sees the invitation", b"Night Shift" in r.data)
with app.app_context():
    m_ada = query("""SELECT tm.id FROM team_members tm JOIN users u ON u.id=tm.user_id
                      WHERE u.email='ada@v4.test'""", one=True)
    m_kem = query("""SELECT tm.id FROM team_members tm JOIN users u ON u.id=tm.user_id
                      WHERE u.email='kemi@v4.test'""", one=True)
ada.post(f"/teams/invites/{m_ada['id']}/accept", follow_redirects=True)
kem.post(f"/teams/invites/{m_kem['id']}/decline", follow_redirects=True)
with app.app_context():
    step("accept and decline both land", scalar(
        "SELECT COUNT(*) FROM team_members WHERE status='active'") == 2 and scalar(
        "SELECT COUNT(*) FROM team_members WHERE status='declined'") == 1)

outsider = student("Nosy One", "nosy@v4.test")
step("a non-member cannot open the team",
     outsider.get(f"/teams/{team['id']}").status_code == 403)

# team applies for the brief
r = led.post(f"/student/projects/{proj['id']}/apply", data={
    "team_id": str(team["id"]),
    "message": "We are two final-year students with Flask and charting experience."},
    follow_redirects=True)
with app.app_context():
    appn = query("SELECT * FROM project_applications", one=True)
step("team application recorded", appn and appn["team_id"] == team["id"])
with app.app_context():
    step("team marked as applied",
         query("SELECT status FROM teams", one=True)["status"] == "applied")

r = ada.post(f"/student/projects/{proj['id']}/apply", data={
    "team_id": str(team["id"]), "message": "x" * 40}, follow_redirects=True)
step("a non-lead cannot apply for the team", b"do not lead that team" in r.data)

co.post(f"/company/applications/{appn['id']}/accept", follow_redirects=True)
with app.app_context():
    placements = query("SELECT * FROM assignments ORDER BY id")
step("every team member got a placement", len(placements) == 2, len(placements))
step("placements carry the team", all(p["team_id"] == team["id"] for p in placements))
with app.app_context():
    step("team is now active",
         query("SELECT status FROM teams", one=True)["status"] == "active")
    step("phases created per member",
         scalar("SELECT COUNT(*) FROM milestones") == 8)

# ------------------------------------------------------- 2. deliverables
r = co.post(f"/deliverables/project/{proj['id']}/new", data={
    "title": "Working prototype with login", "description": "Auth plus the chart page.",
    "due_date": "2026-11-30"}, follow_redirects=True)
with app.app_context():
    d = query("SELECT * FROM deliverables", one=True)
step("company creates a deliverable", bool(d) and d["status"] == "draft")

r = co.post(f"/deliverables/project/{proj['id']}/new", data={
    "title": "Too late", "due_date": "2027-06-01"}, follow_redirects=True)
step("a due date past the brief deadline is refused", b"after the brief" in r.data)

with app.app_context():
    led_asg = query("""SELECT a.id FROM assignments a JOIN users u ON u.id=a.student_id
                        WHERE u.email='tunde@v4.test'""", one=True)
r = led.get(f"/student/work/{led_asg['id']}")
step("draft deliverable hidden from students", b"Working prototype" not in r.data)

step("a student cannot manage deliverables",
     led.get(f"/deliverables/project/{proj['id']}").status_code == 403)

co.post(f"/deliverables/{d['id']}/publish", follow_redirects=True)
r = led.get(f"/student/work/{led_asg['id']}")
step("published deliverable appears for students", b"Working prototype" in r.data)

r = co.post(f"/deliverables/{d['id']}/delete", follow_redirects=True)
step("published deliverable cannot be deleted", b"cannot be deleted" in r.data)

# ------------------------------------- team submission needs everyone's sign-off
r = led.post(f"/student/work/{led_asg['id']}", data={
    "notes": "First cut of the prototype.", "deliverable_id": str(d["id"]),
    "files": [(io.BytesIO(b"zip bytes"), "prototype.zip")]},
    content_type="multipart/form-data", follow_redirects=True)
with app.app_context():
    sub = query("SELECT * FROM submissions", one=True)
step("team submission waits for the team", sub and sub["stage"] == "awaiting_team",
     sub and sub["stage"])
step("submission linked to the deliverable", sub["deliverable_id"] == d["id"])
with app.app_context():
    step("one confirmation requested",
         scalar("SELECT COUNT(*) FROM submission_confirmations") == 1)

r = ada.post(f"/student/submissions/{sub['id']}/reject",
             data={"comment": "The CSV export is missing."}, follow_redirects=True)
with app.app_context():
    step("a rejection sends it back",
         query("SELECT stage FROM submissions", one=True)["stage"] == "changes_requested")

# second attempt, confirmed this time
with app.app_context():
    execute("DELETE FROM submission_confirmations")
    execute("DELETE FROM submissions")
led.post(f"/student/work/{led_asg['id']}", data={
    "notes": "CSV export added.", "deliverable_id": str(d["id"]),
    "files": [(io.BytesIO(b"zip bytes v2"), "prototype.zip")]},
    content_type="multipart/form-data", follow_redirects=True)
with app.app_context():
    sub = query("SELECT * FROM submissions", one=True)

step("teammate cannot be impersonated",
     outsider.post(f"/student/submissions/{sub['id']}/confirm").status_code == 403)

ada.post(f"/student/submissions/{sub['id']}/confirm", follow_redirects=True)
with app.app_context():
    sub = query("SELECT * FROM submissions", one=True)
step("all confirmed, so it goes to the company", sub["stage"] == "with_company",
     sub["stage"])

r = co.get(f"/company/submissions/{sub['id']}")
step("company can review the team's work", r.status_code == 200 and b"prototype.zip" in r.data)

print(f"\n{P} passed, {F} failed")
