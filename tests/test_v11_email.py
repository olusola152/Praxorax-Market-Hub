"""Email alerts, against a real SMTP server running on localhost.

Nothing is mocked: aiosmtpd accepts the messages and we read what arrived.
Run after seed_demo.py.
"""
import asyncio, email, os, threading, time
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up11",
                  MAIL_ENABLED="true", MAIL_HOST="127.0.0.1", MAIL_PORT="8025",
                  MAIL_FROM="alerts@praxorax.test", MAIL_STARTTLS="false",
                  MAIL_SSL="false", MAIL_SYNCHRONOUS="true", BASE_URL="http://localhost:5000")

from aiosmtpd.controller import Controller

INBOX = []


class Collector:
    async def handle_DATA(self, server, session, envelope):
        INBOX.append(email.message_from_bytes(envelope.original_content))
        return "250 OK"


controller = Controller(Collector(), hostname="127.0.0.1", port=8025)
controller.start()
time.sleep(0.4)

from app import app
from db import query, execute, scalar
import mailer
app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


def body_of(msg):
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            return part.get_payload(decode=True).decode()
    return ""


def html_of(msg):
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode()
    return ""


with app.app_context():
    step("mail reports itself configured", mailer.configured(app))
    student = query("SELECT * FROM users WHERE email='ada@demo.marketplace'", one=True)
    execute("UPDATE users SET email_notifications=TRUE")

# ------------------------------------------------------------ one alert
INBOX.clear()
with app.test_request_context():
    from workflow import notify
    notify(student["id"], "Dr Bello asked for corrections on \"Pharmacy inventory "
                          "system\". The CSV export is missing.",
           "/student/work/1")
time.sleep(0.5)

step("an email actually arrived", len(INBOX) == 1, len(INBOX))
msg = INBOX[0] if INBOX else None
step("addressed to the right person", msg and student["email"] in msg["To"])
step("from the configured address", msg and "alerts@praxorax.test" in msg["From"])
step("sender shows the brand", msg and "PraxoraX" in msg["From"])
step("subject is readable", msg and "corrections" in msg["Subject"],
     msg["Subject"] if msg else "")
step("subject carries the brand", msg and "PraxoraX" in msg["Subject"])
step("subject is plain ascii, not encoded", msg and "=?utf-8?" not in msg["Subject"])
step("plain text part present", msg and "CSV export is missing" in body_of(msg))
step("html part present", msg and "CSV export is missing" in html_of(msg))
step("link points at the page", msg and "http://localhost:5000/student/work/1" in body_of(msg))
step("tells them how to stop it", msg and "settings" in body_of(msg).lower())

with app.app_context():
    row = query("""SELECT emailed_at FROM notifications WHERE user_id=%s
                    ORDER BY id DESC LIMIT 1""", (student["id"],), one=True)
step("the send is recorded on the notification", row["emailed_at"] is not None)

# ------------------------------------------------------- opting out works
INBOX.clear()
with app.app_context():
    execute("UPDATE users SET email_notifications=FALSE WHERE id=%s", (student["id"],))
    before = scalar("SELECT COUNT(*) FROM notifications WHERE user_id=%s",
                    (student["id"],))
with app.test_request_context():
    notify(student["id"], "Another thing happened.", "/student/dashboard")
time.sleep(0.4)
step("no email after opting out", len(INBOX) == 0, len(INBOX))
with app.app_context():
    after = scalar("SELECT COUNT(*) FROM notifications WHERE user_id=%s",
                   (student["id"],))
step("but the in-app alert is still saved", after == before + 1)

# --------------------------------------------------- the switch in the UI
c = app.test_client()
c.post("/login", data={"email": "ada@demo.marketplace", "password": "demo1234"})
r = c.get("/student/notifications")
step("the switch is on the notifications page", b"Also email me" in r.data)
step("it reflects being off", b'name="email_notifications" style="width:auto"\n               >' in r.data
     or b"checked" not in r.data.split(b"email_notifications")[1][:80])

r = c.post("/settings/email-alerts", data={"email_notifications": "on"},
           follow_redirects=True)
with app.app_context():
    step("turning it back on saves",
         query("SELECT email_notifications FROM users WHERE id=%s",
               (student["id"],), one=True)["email_notifications"] is True)
step("and says so", b"whenever something needs your attention" in r.data)

INBOX.clear()
with app.test_request_context():
    notify(student["id"], "Back on again.", "/student/dashboard")
time.sleep(0.4)
step("emails resume", len(INBOX) == 1)

# ------------------------------------------ a dead server must not break us
INBOX.clear()
app.config["MAIL_PORT"] = 9999          # nothing listening
with app.app_context():
    before = scalar("SELECT COUNT(*) FROM notifications")
with app.test_request_context():
    notify(student["id"], "Server is down but this must still land.", "/x")
with app.app_context():
    after = scalar("SELECT COUNT(*) FROM notifications")
step("a dead mail server does not lose the alert", after == before + 1)
with app.app_context():
    row = query("SELECT emailed_at FROM notifications ORDER BY id DESC LIMIT 1", one=True)
step("and the failure is recorded as not emailed", row["emailed_at"] is None)
app.config["MAIL_PORT"] = 8025

# ------------------------------------------- mail off entirely is harmless
INBOX.clear()
app.config["MAIL_ENABLED"] = False
with app.app_context():
    before = scalar("SELECT COUNT(*) FROM notifications")
with app.test_request_context():
    notify(student["id"], "Mail is switched off here.", "/x")
time.sleep(0.3)
with app.app_context():
    after = scalar("SELECT COUNT(*) FROM notifications")
step("alerts still work with mail off", after == before + 1)
step("and nothing is sent", len(INBOX) == 0)
app.config["MAIL_ENABLED"] = True

# --------------------------------------- a real event, end to end by email
INBOX.clear()
with app.app_context():
    execute("UPDATE universities SET subscription_status='active'")
    execute("UPDATE companies SET subscription_status='active', "
            "verification_status='verified'")
    execute("UPDATE users SET email_notifications=TRUE")
    asg = query("""SELECT a.id, u.email AS student_email, lu.email AS lecturer_email
                     FROM assignments a JOIN users u ON u.id=a.student_id
                     JOIN users lu ON lu.id=a.lecturer_id
                    WHERE a.lecturer_id IS NOT NULL
                      AND a.status NOT IN ('completed','cancelled') LIMIT 1""", one=True)
    execute("DELETE FROM submissions WHERE assignment_id=%s", (asg["id"],))

import io
st = app.test_client()
st.post("/login", data={"email": asg["student_email"], "password": "demo1234"})
st.post(f"/student/work/{asg['id']}", data={
    "notes": "Done.", "files": [(io.BytesIO(b"x"), "a.pdf")]},
    content_type="multipart/form-data", follow_redirects=True)
time.sleep(0.5)
step("submitting emails the supervisor",
     any(asg["lecturer_email"] in (m["To"] or "") for m in INBOX), len(INBOX))

INBOX.clear()
with app.app_context():
    sub = query("SELECT id FROM submissions WHERE assignment_id=%s", (asg["id"],), one=True)
lc = app.test_client()
lc.post("/login", data={"email": asg["lecturer_email"], "password": "demo1234"})
lc.post(f"/lecturer/submissions/{sub['id']}",
        data={"action": "request_correction", "comment": "The export is missing."},
        follow_redirects=True)
time.sleep(0.5)
step("requesting corrections emails the student",
     any(asg["student_email"] in (m["To"] or "") for m in INBOX), len(INBOX))
if INBOX:
    target = next(m for m in INBOX if asg["student_email"] in (m["To"] or ""))
    step("that email carries the reason", "export is missing" in body_of(target))

# ------------------------------------------------- welcome on signing up
import uuid
for role, data, note in [
    ("student", {"role": "student", "fullname": "New Student",
                 "password": "password123", "confirm": "password123"}, "browse"),
    ("company", {"role": "company", "company_name": "New Co",
                 "fullname": "New Boss", "password": "password123",
                 "confirm": "password123"}, "verify"),
    ("university", {"role": "university", "university_name": "New Uni",
                    "fullname": "New Registrar", "city": "Lagos",
                    "password": "password123", "confirm": "password123"}, "passcode"),
]:
    INBOX.clear()
    address = f"{role}-{uuid.uuid4().hex[:8]}@welcome.test"
    payload = dict(data, email=address)
    if role == "student":
        with app.app_context():
            payload["field_id"] = str(query("SELECT id FROM fields LIMIT 1",
                                            one=True)["id"])
    fresh = app.test_client()
    fresh.post("/register", data=payload, follow_redirects=True)
    time.sleep(0.5)
    step(f"{role} gets a welcome email", len(INBOX) == 1, len(INBOX))
    if INBOX:
        msg = INBOX[0]
        step(f"  addressed to the new {role}", address in (msg["To"] or ""))
        step(f"  subject welcomes them", "Welcome to PraxoraX" == msg["Subject"],
             msg["Subject"])
        step(f"  body tells a {role} what to do next",
             note in body_of(msg).lower(), body_of(msg)[:70])

controller.stop()
print(f"\n{P} passed, {F} failed")
