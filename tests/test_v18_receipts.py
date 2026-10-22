"""Confirmation emails. Run after seed_demo.py.

The platform emailed the other party and never the person who acted, so a
company posting a brief or a student submitting work heard nothing back and
had no way to tell whether it had landed.

Sent against a real SMTP server rather than a mock, so a message counted here
is one that actually left.
"""
import email as emaillib
import os
import time

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up18",
                  TRIAL_DAYS="0", IDLE_TIMEOUT_MINUTES="20",
                  MAIL_ENABLED="true", MAIL_HOST="127.0.0.1", MAIL_PORT="8027",
                  MAIL_FROM="alerts@praxorax.test", MAIL_STARTTLS="false",
                  MAIL_SSL="false", MAIL_SYNCHRONOUS="true",
                  BASE_URL="https://praxorax.test")

from aiosmtpd.controller import Controller

INBOX = []


class Collector:
    async def handle_DATA(self, server, session, envelope):
        INBOX.append(emaillib.message_from_bytes(envelope.original_content))
        return "250 OK"


controller = Controller(Collector(), hostname="127.0.0.1", port=8027)
controller.start()
time.sleep(0.4)

import mailer
from app import app
from db import execute, query, scalar

app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


def plain(msg):
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            return part.get_payload(decode=True).decode()
    return ""


def html(msg):
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode()
    return ""


def to_of(msg):
    return msg["To"]


def login(address, password="demo1234"):
    c = app.test_client()
    c.post("/login", data={"email": address, "password": password})
    return c


# ---------------------------------------------------------- the welcome note
print("\n--- welcoming someone ---\n")

with app.app_context():
    execute("DELETE FROM users WHERE email=%s", ("newcomer@v18.test",))
    FIELD = query("SELECT id FROM fields LIMIT 1", one=True)["id"]

INBOX.clear()
newcomer = app.test_client()
newcomer.post("/register",
              data={"role": "student", "fullname": "New Comer",
                    "email": "newcomer@v18.test", "password": "password123",
                    "confirm": "password123", "field_id": str(FIELD)},
              follow_redirects=True)

step("signing up sends one message", len(INBOX) == 1, len(INBOX))
if INBOX:
    msg = INBOX[0]
    text, markup = plain(msg), html(msg)
    step("to the person who signed up", "newcomer@v18.test" in to_of(msg))
    step("the subject welcomes them", "Welcome to PraxoraX" in str(msg["Subject"]))
    step("it says what the platform is",
         "real work for real companies" in text)
    step("and what they get out of it",
         "record an employer can check" in text)
    step("it tells them the first thing to do", "Finish your profile" in text)
    step("and that they pay nothing", "pay nothing" in text)
    step("the brand is the configured one, not hardcoded",
         "{brand}" not in text and "PraxoraX" in text)

    # A multi-paragraph message has to arrive as paragraphs.
    flat = text.replace("\r\n", "\n")
    step("the plain text keeps its paragraphs", "\n\n" in flat)
    step("and the HTML version does too", markup.count("<p style") >= 4,
         markup.count("<p style"))
    step("nothing is rendered as one wall of text",
         "</p><p" in markup.replace("\n", ""))

with app.app_context():
    step("every role has welcome copy",
         set(mailer.WELCOME) >= {"student", "company", "university",
                                 "lecturer", "admin"})
    step("none of it promises a trial that may not exist",
         all("trial" not in b for b in mailer.WELCOME.values()))
    step("and all of it reads the brand from configuration",
         all("{brand}" in b for b in mailer.WELCOME.values()))

# --------------------------------------------------- posting work as a company
print("\n--- a company posts a brief ---\n")

with app.app_context():
    # Verified, because an unverified company can only draft and a draft
    # sends nobody anything — which is the right behaviour, not the thing
    # under test here.
    execute("""UPDATE companies SET verification_status='verified',
                      subscription_status='active'
                WHERE user_id=(SELECT id FROM users WHERE email='hr@demo.marketplace')""")
    field = query("SELECT id FROM fields LIMIT 1", one=True)["id"]
    SKILL_ID = query("SELECT id FROM skills LIMIT 1", one=True)["id"]

INBOX.clear()
co = login("hr@demo.marketplace")
r = co.post("/company/projects/new",
            data={"title": "Receipt Test Brief", "description": "x" * 80,
                  "field_id": str(field), "difficulty": "intermediate",
                  "deadline": "2027-06-30", "max_students": "2",
                  "skills": [str(SKILL_ID)], "publish": "on"},
            follow_redirects=True)
step("the brief is posted", r.status_code == 200)

mine = [m for m in INBOX if "hr@demo.marketplace" in to_of(m)]
step("the company is emailed a confirmation", len(mine) == 1, len(INBOX))
if mine:
    step("naming the brief", "Receipt Test Brief" in str(mine[0]["Subject"]))
    step("and saying what happens next", "lecturers" in plain(mine[0]).lower())

# ------------------------------------------------------ a student applies
print("\n--- a student applies ---\n")

with app.app_context():
    proj = query("SELECT id, title FROM projects WHERE title='Receipt Test Brief'",
                 one=True)
    skill = query("SELECT id FROM skills LIMIT 1", one=True)["id"]

newcomer.post("/student/profile",
              data={"bio": "Final year student building Flask tools. I have "
                           "shipped two reporting dashboards for small firms.",
                    "level": "400"}, follow_redirects=True)
newcomer.post("/student/skills", data={"skills": [str(skill)]},
              follow_redirects=True)

INBOX.clear()
newcomer.post(f"/student/projects/{proj['id']}/apply",
              data={"message": "I have built reporting dashboards and can start "
                               "on this immediately."},
              follow_redirects=True)

mine = [m for m in INBOX if "newcomer@v18.test" in to_of(m)]
step("the student gets a receipt for the application", len(mine) == 1, len(INBOX))
if mine:
    step("naming the brief", "Receipt Test Brief" in str(mine[0]["Subject"]))
    step("and saying who has it now", "demo" in plain(mine[0]).lower()
         or "Technologies" in plain(mine[0]) or "Ltd" in plain(mine[0]))

step("and the company still hears about it separately",
     any("hr@demo.marketplace" in to_of(m) for m in INBOX))

# --------------------------------------------------- the company decides
print("\n--- the company decides ---\n")

with app.app_context():
    appn = query("""SELECT id FROM project_applications
                     WHERE project_id=%s ORDER BY id DESC LIMIT 1""",
                 (proj["id"],), one=True)
INBOX.clear()
co.post(f"/company/applications/{appn['id']}/accept", follow_redirects=True)
step("the company is told what it just did",
     any("hr@demo.marketplace" in to_of(m) for m in INBOX), len(INBOX))
step("and the student is told too",
     any("newcomer@v18.test" in to_of(m) for m in INBOX))

# ------------------------------------------------------ submitting work
print("\n--- a student submits work ---\n")

with app.app_context():
    asg = query("""SELECT id FROM assignments WHERE student_id=(
                     SELECT id FROM users WHERE email='newcomer@v18.test')
                   ORDER BY id DESC LIMIT 1""", one=True)
if asg:
    INBOX.clear()
    newcomer.post(f"/student/work/{asg['id']}",
                  data={"repo_url": "https://github.com/example/work",
                        "notes": "First version."},
                  follow_redirects=True)
    mine = [m for m in INBOX if "newcomer@v18.test" in to_of(m)]
    step("the student gets proof the work left", len(mine) == 1, len(INBOX))
    if mine:
        step("naming the project", "Receipt Test Brief" in str(mine[0]["Subject"]))
        step("and saying who has it", "received" in plain(mine[0]).lower())
else:
    step("a placement exists to submit against", False, "none found")

# ------------------------------------------------------- sending an invite
print("\n--- inviting someone to a team ---\n")

lead = login("ada@demo.marketplace")
lead.post("/teams/new", data={"name": "Receipt Team"}, follow_redirects=True)
with app.app_context():
    team = query("SELECT id FROM teams WHERE name='Receipt Team' ORDER BY id DESC",
                 one=True)["id"]

INBOX.clear()
lead.post(f"/teams/{team}/invite", data={"email": "outsider@v18.test"},
          follow_redirects=True)
step("the invited address is emailed",
     any("outsider@v18.test" in to_of(m) for m in INBOX), len(INBOX))
mine = [m for m in INBOX if "ada@demo.marketplace" in to_of(m)]
step("and the person who sent it gets a receipt", len(mine) == 1, len(INBOX))
if mine:
    step("naming who was invited", "outsider@v18.test" in plain(mine[0]))
    step("and saying they are not here yet", "not on" in plain(mine[0]))

INBOX.clear()
lead.post(f"/teams/{team}/invite", data={"email": "chidi@demo.marketplace"},
          follow_redirects=True)
mine = [m for m in INBOX if "ada@demo.marketplace" in to_of(m)]
step("inviting someone who is already here also confirms", len(mine) == 1,
     len(INBOX))
if mine:
    step("naming them", "Chidi" in plain(mine[0]) or "chidi" in plain(mine[0]).lower())

# ----------------------------------------------- respecting the switch
print("\n--- the switch is still the switch ---\n")

with app.app_context():
    execute("""UPDATE users SET email_notifications = FALSE
                WHERE email='newcomer@v18.test'""")
INBOX.clear()
newcomer.post(f"/student/projects/{proj['id']}/apply",
              data={"message": "Applying again to check the email switch works."},
              follow_redirects=True)
step("someone who turned email off gets no receipt",
     not any("newcomer@v18.test" in to_of(m) for m in INBOX), len(INBOX))
with app.app_context():
    execute("""UPDATE users SET email_notifications = TRUE
                WHERE email='newcomer@v18.test'""")

# A receipt must never be the thing that breaks the action.
app.config["MAIL_HOST"] = "127.0.0.1"
app.config["MAIL_PORT"] = 9
r = co.post("/company/projects/new",
            data={"title": "Posted While Mail Is Down", "description": "y" * 80,
                  "field_id": str(field), "difficulty": "intermediate",
                  "deadline": "2027-06-30", "max_students": "1",
                  "skills": [str(SKILL_ID)], "publish": "on"},
            follow_redirects=True)
step("a dead mail server does not stop the work", r.status_code == 200)
with app.app_context():
    step("and the brief is published anyway",
         scalar("SELECT COUNT(*) FROM projects WHERE title='Posted While Mail Is Down'") == 1)
app.config["MAIL_PORT"] = 8027

controller.stop()
print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
