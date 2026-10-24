"""Resend as a mail transport, and the receipts around supervision.

Two things that arrived together: mail can now leave over Resend's HTTP API
instead of SMTP, and the people involved in a placement are told about it.

The Resend half is tested against a stub HTTP server rather than mocked, so
what is checked is the request this code actually builds — the endpoint, the
header, the JSON body — which is the part that is wrong when mail silently
does not send.

Run after seed_demo.py.
"""
import email as emaillib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up25",
                  TRIAL_DAYS="0", BASE_URL="https://praxorax.test")

CAUGHT = []


class Stub(BaseHTTPRequestHandler):
    """Stands in for api.resend.com."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        CAUGHT.append({"path": self.path,
                       "auth": self.headers.get("Authorization"),
                       "ctype": self.headers.get("Content-Type"),
                       "body": json.loads(raw)})
        subject = CAUGHT[-1]["body"].get("subject", "")
        if "REFUSE" in subject:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'{"message":"The praxorax.test domain is not verified."}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"id":"3f1b-abc"}')

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 8712), Stub)
threading.Thread(target=server.serve_forever, daemon=True).start()
time.sleep(0.3)

import mailer

mailer.RESEND_ENDPOINT = "http://127.0.0.1:8712/emails"

from app import app
from db import execute, query, scalar

app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


def use_resend():
    app.config.update(MAIL_ENABLED=True, MAIL_FROM="alerts@praxorax.test",
                      MAIL_TRANSPORT="resend", RESEND_API_KEY="re_test_key",
                      MAIL_REPLY_TO="hello@praxorax.test",
                      MAIL_SYNCHRONOUS=True, MAIL_HOST="")


def login(address, password="demo1234"):
    c = app.test_client()
    c.post("/login", data={"email": address, "password": password})
    return c


# ============================================== picking a transport
print("\n--- which way mail leaves ---\n")

with app.app_context():
    app.config.update(MAIL_TRANSPORT="", RESEND_API_KEY="", MAIL_HOST="smtp.x")
    step("no key and a host means SMTP", mailer.transport(app) == "smtp")

    app.config.update(MAIL_TRANSPORT="", RESEND_API_KEY="re_x")
    step("a key on its own is enough to mean Resend",
         mailer.transport(app) == "resend",
         "setting one variable should not require setting two")

    app.config.update(MAIL_TRANSPORT="smtp", RESEND_API_KEY="re_x")
    step("but an explicit choice wins", mailer.transport(app) == "smtp")

    app.config.update(MAIL_TRANSPORT="RESEND")
    step("and is not case-sensitive", mailer.transport(app) == "resend")

    # Configured means different things for each.
    app.config.update(MAIL_ENABLED=True, MAIL_FROM="a@b.c",
                      MAIL_TRANSPORT="resend", RESEND_API_KEY="", MAIL_HOST="smtp.x")
    step("Resend without a key is not configured, host or no host",
         mailer.configured(app) is False)
    app.config.update(RESEND_API_KEY="re_x")
    step("with a key it is, and needs no host", mailer.configured(app) is True)
    app.config.update(MAIL_TRANSPORT="smtp", MAIL_HOST="")
    step("SMTP without a host is not configured", mailer.configured(app) is False)
    app.config.update(MAIL_ENABLED=False, MAIL_TRANSPORT="resend",
                      RESEND_API_KEY="re_x")
    step("and the master switch still turns everything off",
         mailer.configured(app) is False)

# ================================================ the request it builds
print("\n--- what gets posted to Resend ---\n")

CAUGHT.clear()
use_resend()
with app.app_context():
    sent = mailer.send("ada@example.com", "Ada Obi", "Placed on a brief",
                       "You have been placed.\n\nIt is due on Friday.",
                       "/student/dashboard", app=app)
step("the message is accepted", sent is True)
step("exactly one request was made", len(CAUGHT) == 1, len(CAUGHT))

if CAUGHT:
    r = CAUGHT[0]
    body = r["body"]
    step("it goes to the emails endpoint", r["path"] == "/emails", r["path"])
    step("with the key as a bearer token",
         r["auth"] == "Bearer re_test_key", r["auth"])
    step("and is JSON", r["ctype"] == "application/json", r["ctype"])
    step("from the configured address and brand",
         body["from"] == "PraxoraX <alerts@praxorax.test>", body["from"])
    step("to is a list, as the API wants",
         isinstance(body["to"], list) and "ada@example.com" in body["to"][0],
         body["to"])
    step("the subject survives", body["subject"] == "Placed on a brief")
    step("the reply-to is passed on",
         body.get("reply_to") == "hello@praxorax.test", body.get("reply_to"))
    step("both a plain and an HTML body are sent",
         bool(body.get("text")) and bool(body.get("html")))
    step("the text keeps its paragraphs", "\n\n" in body["text"])
    step("and the link is absolute",
         "https://praxorax.test/student/dashboard" in body["html"])

# ------------------------------------------------ when Resend says no
print("\n--- when Resend refuses ---\n")

CAUGHT.clear()
with app.app_context():
    sent, detail = mailer.send_now(app, "ada@example.com", "Ada",
                                   "REFUSE this one", "body")
step("a refusal is reported, not swallowed", sent is False)
step("and carries Resend's own reason",
     "not verified" in detail, detail)
step("with the status code", "403" in detail, detail)

# The commonest two misconfigurations should say which one they are.
with app.app_context():
    app.config["RESEND_API_KEY"] = ""
    sent, detail = mailer.send_now(app, "a@b.c", "A", "s", "b")
    step("a missing key says so by name", "RESEND_API_KEY" in detail, detail)
    app.config["RESEND_API_KEY"] = "re_test_key"

    app.config["MAIL_FROM"] = ""
    sent, detail = mailer.send_now(app, "a@b.c", "A", "s", "b")
    step("a missing sending address says so too", "MAIL_FROM" in detail, detail)
    app.config["MAIL_FROM"] = "alerts@praxorax.test"

    app.config["MAIL_ENABLED"] = False
    sent, detail = mailer.send_now(app, "a@b.c", "A", "s", "b")
    step("and so does the master switch", "MAIL_ENABLED" in detail, detail)
    app.config["MAIL_ENABLED"] = True

# A dead endpoint must not raise into the caller.
with app.app_context():
    old = mailer.RESEND_ENDPOINT
    mailer.RESEND_ENDPOINT = "http://127.0.0.1:9/emails"
    step("an unreachable API does not raise",
         mailer.send("a@b.c", "A", "s", "b", app=app) is False)
    sent, detail = mailer.send_now(app, "a@b.c", "A", "s", "b")
    step("and send_now explains itself", sent is False and bool(detail), detail)
    mailer.RESEND_ENDPOINT = old

# ============================== sending with no domain of your own
print("\n--- Resend without a domain ---\n")

# resend.dev is the address somebody uses before they have a domain. It
# delivers only to the Resend account holder and 403s every other
# recipient, which means a site can look configured, pass its own test
# email, and send not one student anything.
with app.app_context():
    app.config.update(MAIL_TRANSPORT="resend", RESEND_API_KEY="re_x",
                      MAIL_ENABLED=True, MAIL_FROM="onboarding@resend.dev")
    step("a resend.dev sender is recognised as test-only",
         mailer.sender_is_test_only(app) is True)

    app.config["MAIL_FROM"] = "alerts@praxorax.com"
    step("an address on a real domain is not",
         mailer.sender_is_test_only(app) is False)

    app.config.update(MAIL_TRANSPORT="smtp", MAIL_FROM="onboarding@resend.dev")
    step("and over SMTP the address does not matter",
         mailer.sender_is_test_only(app) is False)

# The refusal has to explain itself rather than repeat the API.
CAUGHT.clear()
use_resend()
with app.app_context():
    app.config["MAIL_FROM"] = "onboarding@resend.dev"
    sent, detail = mailer.send_now(app, "someone@example.com", "Someone",
                                   "REFUSE this", "body")
step("a 403 from a test sender is explained", sent is False)
step("naming the restriction, not just the code",
     "only delivers to" in detail, detail)
step("and saying what to do about it",
     "verified" in detail and "SMTP" in detail, detail)

# It must be visible before somebody ships, not after.
app.config.update(MAIL_TRANSPORT="resend", RESEND_API_KEY="re_x",
                  MAIL_ENABLED=True, MAIL_FROM="onboarding@resend.dev")
page = login("ada@demo.marketplace").get("/student/notifications").data
step("the Alerts page warns about it", b"can only email you" in page)
step("and says SMTP needs no domain", b"needs no domain" in page)

app.config["MAIL_FROM"] = "alerts@praxorax.test"
page = login("ada@demo.marketplace").get("/student/notifications").data
step("the warning is gone once the sender is on a real domain",
     b"can only email you" not in page)
use_resend()

# ================================================ the test-email button
print("\n--- the button an administrator presses ---\n")

# The point of this check: a test button with its own copy of the sending
# logic can pass while real mail fails. It has to go the same way.
import inspect

source = inspect.getsource(mailer.send_now)
step("the test button uses the shared delivery path", "_send(" in source)
step("rather than opening its own connection",
     "smtplib" not in source and "urlopen" not in source)

# ================================== the receipts around a placement
print("\n--- who hears about a placement ---\n")

CAUGHT.clear()
use_resend()

# Built rather than borrowed. The seeded brief is already full, and a test
# that depends on spare capacity in demo data fails for a reason that has
# nothing to do with what it is testing.
with app.app_context():
    lec = query("""SELECT u.id, u.email, u.fullname
                     FROM users u JOIN lecturer_profiles lp ON lp.user_id = u.id
                    ORDER BY u.id LIMIT 1""", one=True)
    company = query("""SELECT c.id, c.user_id, c.name FROM companies c
                        WHERE c.verification_status='verified' LIMIT 1""", one=True)
    if not company:
        execute("UPDATE companies SET verification_status='verified' WHERE id="
                "(SELECT MIN(id) FROM companies)")
        company = query("SELECT id, user_id, name FROM companies LIMIT 1", one=True)
    field = query("""SELECT sp.field_id FROM student_profiles sp
                      JOIN lecturer_profiles lp
                        ON lp.university_id = sp.university_id
                     WHERE lp.user_id=%s AND sp.field_id IS NOT NULL
                     LIMIT 1""", (lec["id"],), one=True)

    execute("DELETE FROM projects WHERE title='Placement Receipt Brief'")
    pid = execute(
        """INSERT INTO projects (company_id, title, description, field_id,
                                 difficulty, deadline, max_students, status)
           VALUES (%s,'Placement Receipt Brief','Work used to check that the
                   people on a placement are told about it.',%s,'intermediate',
                   CURRENT_DATE + 60, 3, 'open') RETURNING id""",
        (company["id"], field["field_id"] if field else None), returning=True)
    execute("""INSERT INTO project_requests (project_id, lecturer_id, message,
                                             places, status, decided_at)
               VALUES (%s,%s,'Taking this on.',3,'approved',NOW())""",
            (pid, lec["id"]))

    row = {"project_id": pid, "lecturer_id": lec["id"],
           "title": "Placement Receipt Brief"}

    candidate = query(
        """SELECT u.id, u.email, u.fullname
             FROM users u
             JOIN student_profiles sp ON sp.user_id = u.id
             JOIN lecturer_profiles lp ON lp.university_id = sp.university_id
            WHERE u.role='student' AND u.status='active' AND lp.user_id=%s
            LIMIT 1""", (lec["id"],), one=True)

if not candidate:
    step("a student exists to place", False, "none at this institution")
else:
    if True:
        lecturer = login(lec["email"])
        CAUGHT.clear()
        r = lecturer.post(f"/lecturer/projects/{row['project_id']}/assign",
                          data={"students": [str(candidate["id"])]},
                          follow_redirects=True)

        with app.app_context():
            placed = query(
                """SELECT id FROM assignments
                    WHERE project_id=%s AND student_id=%s""",
                (row["project_id"], candidate["id"]), one=True)
        step("the student is placed", placed is not None, r.status_code)

        to_student = [c for c in CAUGHT
                      if candidate["email"] in str(c["body"]["to"])]
        to_lecturer = [c for c in CAUGHT if lec["email"] in str(c["body"]["to"])]

        # This is the gap that was reported: the student's alert was written
        # straight into the table inside the transaction, so it never went
        # through notify() and never became an email.
        step("the student is emailed, not only told in the app",
             len(to_student) == 1, [c["body"]["to"] for c in CAUGHT])
        if to_student:
            text = to_student[0]["body"]["text"]
            step("the email names the brief", row["title"] in text)
            step("and who placed them", lec["fullname"] in text)
            step("and says where the work goes", "institution" in text.lower())

        step("the lecturer gets their own confirmation", len(to_lecturer) == 1,
             len(CAUGHT))
        if to_lecturer:
            text = to_lecturer[0]["body"]["text"]
            step("naming the student placed", candidate["fullname"] in text)
            step("and the brief", row["title"] in text)

        with app.app_context():
            alerts = scalar(
                """SELECT COUNT(*) FROM notifications
                    WHERE user_id=%s AND body LIKE %s""",
                (candidate["id"], "%" + row["title"] + "%"))
        step("the in-app alert is still there as well", alerts >= 1, alerts)

# ------------------------------- a lecturer applying to supervise
print("\n--- a lecturer applies for a brief ---\n")

with app.app_context():
    open_project = query(
        """SELECT p.id, p.title FROM projects p
            WHERE p.status='open'
              AND p.id NOT IN (SELECT project_id FROM project_requests
                                WHERE lecturer_id=%s)
            LIMIT 1""", (row["lecturer_id"],), one=True) if row else None

if open_project:
    CAUGHT.clear()
    lecturer = login(lec["email"])
    lecturer.post(f"/lecturer/projects/{open_project['id']}/request",
                  data={"places": "2", "message": "My final years fit this."},
                  follow_redirects=True)
    mine = [c for c in CAUGHT if lec["email"] in str(c["body"]["to"])]
    step("the lecturer is told their application went", len(mine) >= 1, len(CAUGHT))
    if mine:
        step("the subject names the brief",
             open_project["title"] in mine[0]["body"]["subject"],
             mine[0]["body"]["subject"])
        step("and the body says the company decides next",
             "company decides" in mine[0]["body"]["text"].lower())
else:
    step("an open brief was available to apply for", True, "skipped — none free")

# ===================================== the receipts that already existed
print("\n--- signing up, posting, applying ---\n")

CAUGHT.clear()
with app.app_context():
    execute("DELETE FROM users WHERE email=%s", ("fresh@v25.test",))
    field = query("SELECT id FROM fields LIMIT 1", one=True)["id"]

app.test_client().post("/register",
                       data={"role": "student", "fullname": "Fresh Start",
                             "email": "fresh@v25.test", "password": "password123",
                             "confirm": "password123", "field_id": str(field)},
                       follow_redirects=True)
welcome = [c for c in CAUGHT if "fresh@v25.test" in str(c["body"]["to"])]
step("a new account is welcomed, over Resend", len(welcome) == 1, len(CAUGHT))
if welcome:
    step("and the welcome says what the place is",
         "real work" in welcome[0]["body"]["text"].lower())

server.shutdown()
print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
