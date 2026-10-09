"""One-click project requests, and the clear-placements script.
Run after seed_demo.py."""
import os, subprocess
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up8")

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
    lec = query("SELECT id, fullname FROM users WHERE email='bello@demo.marketplace'",
                one=True)
    execute("DELETE FROM project_requests WHERE lecturer_id=%s", (lec["id"],))
    proj = query("""SELECT p.id, p.title, p.max_students, c.user_id AS company_user_id
                      FROM projects p JOIN companies c ON c.id=p.company_id
                     WHERE p.status='open' LIMIT 1""", one=True)
    before = scalar("SELECT COUNT(*) FROM notifications WHERE user_id=%s",
                    (proj["company_user_id"],))

lc = login("bello@demo.marketplace")

# the whole point: no message, no place count, just a click
r = lc.post(f"/lecturer/projects/{proj['id']}/request", follow_redirects=True)
with app.app_context():
    req = query("""SELECT * FROM project_requests
                    WHERE project_id=%s AND lecturer_id=%s""",
                (proj["id"], lec["id"]), one=True)
step("request created from a bare click", bool(req))
step("no message is fine", req["message"] in (None, ""), repr(req["message"]))
step("places defaults to one", req["places"] == 1, req["places"])
step("it starts pending", req["status"] == "pending", req["status"])

with app.app_context():
    after = scalar("SELECT COUNT(*) FROM notifications WHERE user_id=%s",
                   (proj["company_user_id"],))
    alert = query("""SELECT body, url FROM notifications WHERE user_id=%s
                      ORDER BY id DESC LIMIT 1""", (proj["company_user_id"],), one=True)
step("company was notified", after == before + 1)
step("alert names the lecturer", lec["fullname"] in alert["body"])
step("alert links to a requests page", "requests" in (alert["url"] or ""),
     alert["url"])

# asking twice does not duplicate
r = lc.post(f"/lecturer/projects/{proj['id']}/request", follow_redirects=True)
with app.app_context():
    step("asking twice is refused",
         scalar("""SELECT COUNT(*) FROM project_requests
                    WHERE project_id=%s AND lecturer_id=%s""",
                (proj["id"], lec["id"])) == 1)
step("and says so", b"already asked" in r.data)

# the browse list offers the button without opening the brief
with app.app_context():
    execute("DELETE FROM project_requests WHERE lecturer_id=%s", (lec["id"],))
r = lc.get("/lecturer/projects")
step("browse list has a request button", b"Request this project" in r.data)

r = lc.get(f"/lecturer/projects/{proj['id']}")
step("detail page leads with the button", b"Request this project" in r.data)
step("the note is optional, behind a disclosure", b"Add a note or ask for more places" in r.data)
step("no 40-character rule is imposed", b"minlength=\"40\"" not in r.data)

# the company can accept or decline as before
lc.post(f"/lecturer/projects/{proj['id']}/request", follow_redirects=True)
with app.app_context():
    req = query("""SELECT * FROM project_requests
                    WHERE project_id=%s AND lecturer_id=%s""",
                (proj["id"], lec["id"]), one=True)
    company_email = query("SELECT email FROM users WHERE id=%s",
                          (proj["company_user_id"],), one=True)["email"]

co = login(company_email)
r = co.get("/company/requests")
step("company sees the request", r.status_code == 200 and lec["fullname"].encode() in r.data)

r = co.post(f"/company/requests/{req['id']}/approve", follow_redirects=True)
with app.app_context():
    after_req = query("SELECT status FROM project_requests WHERE id=%s",
                      (req["id"],), one=True)
step("company can approve it", after_req["status"] == "approved", after_req["status"])
with app.app_context():
    lec_alert = query("""SELECT body FROM notifications WHERE user_id=%s
                          ORDER BY id DESC LIMIT 1""", (lec["id"],), one=True)
step("lecturer is told", lec_alert and proj["title"] in lec_alert["body"])

# ------------------------------------------- the clear-placements script
with app.app_context():
    execute("UPDATE projects SET status='engaged' WHERE id=%s", (proj["id"],))

subprocess.run(
    ["su", "postgres", "-c",
     "psql -q -d smtest -f /home/claude/praxorax/database/clear_placements.sql"],
    capture_output=True)

with app.app_context():
    step("placements cleared", scalar("SELECT COUNT(*) FROM assignments") == 0)
    step("submissions cleared", scalar("SELECT COUNT(*) FROM submissions") == 0)
    step("requests cleared", scalar("SELECT COUNT(*) FROM project_requests") == 0)
    step("applications cleared", scalar("SELECT COUNT(*) FROM project_applications") == 0)
    step("phases cleared", scalar("SELECT COUNT(*) FROM milestones") == 0)
    step("briefs are open again",
         scalar("SELECT COUNT(*) FROM projects WHERE status='engaged'") == 0)
    step("accounts survived", scalar("SELECT COUNT(*) FROM users") > 5)
    step("briefs survived", scalar("SELECT COUNT(*) FROM projects") > 0)
    step("universities survived", scalar("SELECT COUNT(*) FROM universities") > 0)

# and the flow still works from scratch afterwards
lc = login("bello@demo.marketplace")
r = lc.post(f"/lecturer/projects/{proj['id']}/request", follow_redirects=True)
with app.app_context():
    step("requesting works again after the reset",
         scalar("SELECT COUNT(*) FROM project_requests") == 1)

print(f"\n{P} passed, {F} failed")
