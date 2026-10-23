"""The three things the client asked for. Run after seed_demo.py.

  * inviting someone to a team before they have an account
  * requiring a profile before a student can apply
  * being able to tell whether email actually works

Email is tested against a real SMTP server on localhost, not a mock, because
the complaint was precisely that the setting said yes and nothing arrived.
"""
import email as emaillib
import os
import time

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up16",
                  TRIAL_DAYS="0", OPEN_STUDENT_SIGNUP="true",
                  IDLE_TIMEOUT_MINUTES="20",
                  MAIL_ENABLED="true", MAIL_HOST="127.0.0.1", MAIL_PORT="8026",
                  MAIL_FROM="alerts@praxorax.test", MAIL_STARTTLS="false",
                  MAIL_SSL="false", MAIL_SYNCHRONOUS="true",
                  BASE_URL="https://praxorax.test")

from aiosmtpd.controller import Controller

INBOX = []


class Collector:
    async def handle_DATA(self, server, session, envelope):
        INBOX.append(emaillib.message_from_bytes(envelope.original_content))
        return "250 OK"


controller = Controller(Collector(), hostname="127.0.0.1", port=8026)
controller.start()
time.sleep(0.4)

import invitations
import profiles
from app import app
from db import execute, query, scalar

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


def login(email_address, password="demo1234"):
    c = app.test_client()
    c.post("/login", data={"email": email_address, "password": password})
    return c


with app.app_context():
    FIELD = query("SELECT id FROM fields ORDER BY id LIMIT 1", one=True)["id"]
    SKILL = query("SELECT id FROM skills ORDER BY id LIMIT 1", one=True)["id"]
    execute("DELETE FROM team_invitations")
    execute("DELETE FROM users WHERE email LIKE %s", ("%@v16.test",))

print("\n--- inviting someone who is not here yet ---\n")

lead = login("ada@demo.marketplace")
lead.post("/teams/new", data={"name": "Review Team"}, follow_redirects=True)
with app.app_context():
    TEAM = query("SELECT id FROM teams WHERE name='Review Team' ORDER BY id DESC",
                 one=True)["id"]

INBOX.clear()
r = lead.post(f"/teams/{TEAM}/invite", data={"email": "stranger@v16.test"},
              follow_redirects=True)
step("an address with no account is accepted", r.status_code == 200)
with app.app_context():
    inv = query("SELECT * FROM team_invitations WHERE email='stranger@v16.test'",
                one=True)
step("an invitation is recorded", inv is not None and inv["status"] == "pending")
step("with a token long enough not to be guessed", len(inv["token"]) >= 24)
step("and an expiry", inv["expires_at"] is not None)

# Two now: the invitation itself, and since v12 a receipt to whoever sent it.
to_invitee = [m for m in INBOX if "stranger@v16.test" in str(m["To"])]
step("the invitation is emailed", len(to_invitee) == 1, len(INBOX))
step("and the sender gets their own confirmation",
     any("ada@demo.marketplace" in str(m["To"]) for m in INBOX))
if to_invitee:
    text = body_of(to_invitee[0])
    step("it names who invited them",
         "Ada" in text or "Ada" in str(to_invitee[0]["Subject"]))
    step("it names the team", "Review Team" in text)
    # Since v19 the link opens the invitation page rather than the signup
    # form: somebody who has never heard of the site reads what it is before
    # being asked for a password. The point of this check is unchanged —
    # the mail carries a working way in, keyed to the token.
    step("and carries the invitation link", f"/invite/{inv['token']}" in text)
    step("the link is the only thing that identifies it",
         "stranger@v16.test" not in text.split("https://")[-1])

r = lead.get(f"/teams/{TEAM}")
step("the team page lists it as waiting", b"stranger@v16.test" in r.data)
step("and offers to withdraw it", b"Withdraw" in r.data)

# The signup page should explain itself to someone who has never been here.
anon = app.test_client()
page = anon.get(f"/register?invite={inv['token']}")
step("the signup page names the inviter", b"invited you" in page.data)
step("and the team", b"Review Team" in page.data)
step("and fills in the address it was sent to", b"stranger@v16.test" in page.data)

r = anon.post(f"/register?invite={inv['token']}",
              data={"role": "student", "fullname": "Stranger Here",
                    "email": "stranger@v16.test", "password": "password123",
                    "confirm": "password123", "field_id": str(FIELD)},
              follow_redirects=True)
step("they can sign up", r.status_code == 200)
step("and are told about the team", b"Review Team" in r.data)

with app.app_context():
    inv2 = query("SELECT status, accepted_by FROM team_invitations WHERE id=%s",
                 (inv["id"],), one=True)
    uid = query("SELECT id FROM users WHERE email='stranger@v16.test'",
                one=True)["id"]
    mem = query("SELECT status FROM team_members WHERE team_id=%s AND user_id=%s",
                (TEAM, uid), one=True)
step("the invitation is used up", inv2["status"] == "accepted")
step("and attributed to them", inv2["accepted_by"] == uid)
# Since v19, signing up through the link they followed puts them on the team
# outright. They read the invitation page and chose to join before the form
# ever appeared, so a third confirmation on arrival was only friction. An
# invitation they did NOT follow still waits to be accepted — v19 covers that.
step("they are on the team", mem is not None, mem)
step("as a member, because following the link was the decision",
     mem is not None and mem["status"] == "active", mem)

with app.app_context():
    told = scalar("""SELECT COUNT(*) FROM notifications n JOIN users u ON u.id=n.user_id
                      WHERE u.email='ada@demo.marketplace' AND n.body LIKE %s""",
                  ("%signed up%",))
step("the person who invited them is told", told >= 1, told)

# Signing up with the invited address but no token must work the same way.
with app.app_context():
    execute("DELETE FROM users WHERE email='plain@v16.test'")
lead.post(f"/teams/{TEAM}/invite", data={"email": "plain@v16.test"})
plain = app.test_client()
plain.post("/register", data={"role": "student", "fullname": "Plain Join",
                              "email": "plain@v16.test", "password": "password123",
                              "confirm": "password123", "field_id": str(FIELD)},
           follow_redirects=True)
with app.app_context():
    row = query("""SELECT ti.status FROM team_invitations ti
                    WHERE ti.email='plain@v16.test'""", one=True)
step("the address alone claims the invitation, token or not",
     row["status"] == "accepted", row["status"])

# Withdrawing.
lead.post(f"/teams/{TEAM}/invite", data={"email": "gone@v16.test"})
with app.app_context():
    doomed = query("SELECT id FROM team_invitations WHERE email='gone@v16.test'",
                   one=True)["id"]
lead.post(f"/teams/{TEAM}/invitations/{doomed}/cancel", follow_redirects=True)
with app.app_context():
    step("an invitation can be withdrawn",
         query("SELECT status FROM team_invitations WHERE id=%s", (doomed,),
               one=True)["status"] == "cancelled")

# An expired invitation is not honoured.
lead.post(f"/teams/{TEAM}/invite", data={"email": "late@v16.test"})
with app.app_context():
    execute("""UPDATE team_invitations SET expires_at = NOW() - INTERVAL '1 day'
                WHERE email='late@v16.test'""")
    late = query("SELECT * FROM team_invitations WHERE email='late@v16.test'",
                 one=True)
    step("an expired invitation is not live", invitations.live(late) is False)
late_c = app.test_client()
late_c.post("/register", data={"role": "student", "fullname": "Too Late",
                               "email": "late@v16.test", "password": "password123",
                               "confirm": "password123", "field_id": str(FIELD)},
            follow_redirects=True)
with app.app_context():
    uid = query("SELECT id FROM users WHERE email='late@v16.test'", one=True)["id"]
    step("and does not put them on the team",
         query("SELECT 1 FROM team_members WHERE team_id=%s AND user_id=%s",
               (TEAM, uid), one=True) is None)

r = lead.post(f"/teams/{TEAM}/invite", data={"email": "ada@demo.marketplace"},
              follow_redirects=True)
step("you cannot invite yourself", b"already on this team" in r.data
     or b"your own address" in r.data)
r = lead.post(f"/teams/{TEAM}/invite", data={"email": "not-an-address"},
              follow_redirects=True)
step("a malformed address is refused", b"email address of the person" in r.data)

print("\n--- a profile a company can judge ---\n")

fresh = app.test_client()
with app.app_context():
    execute("DELETE FROM users WHERE email='raw@v16.test'")
r = fresh.post("/register", data={"role": "student", "fullname": "Raw Recruit",
                                  "email": "raw@v16.test", "password": "password123",
                                  "confirm": "password123", "field_id": str(FIELD)},
               follow_redirects=True)
step("a new student lands on their profile, not the feed",
     b"Finish your profile" in r.data)

with app.app_context():
    RAW = query("SELECT id FROM users WHERE email='raw@v16.test'", one=True)["id"]
    gaps = [k for k, _ in profiles.missing(profiles.profile_of(RAW))]
step("the field chosen at signup already counts", "field_id" not in gaps, gaps)
step("the rest is still wanted", set(gaps) == {"level", "bio", "skills"}, gaps)

with app.app_context():
    brief = query("SELECT id FROM projects WHERE status='open' LIMIT 1", one=True)["id"]
r = fresh.post(f"/student/projects/{brief}/apply",
               data={"message": "I would like to build this because it fits my course."},
               follow_redirects=True)
step("applying is refused while the profile is thin",
     b"Finish your profile before applying" in r.data)
step("and says exactly what is missing",
     b"Say what level you are at" in r.data and b"at least one skill" in r.data)
with app.app_context():
    step("no application was recorded",
         scalar("SELECT COUNT(*) FROM project_applications WHERE student_id=%s",
                (RAW,)) == 0)

r = fresh.post("/student/profile",
               data={"bio": "Final year computer science student. I build Flask "
                            "web apps and have shipped two inventory systems for "
                            "small businesses in Lagos.",
                     "level": "400", "department": "Computer Science"},
               follow_redirects=True)
step("saving a partial profile says what is left", b"Still needed" in r.data)
with app.app_context():
    step("and it is not yet complete", not profiles.is_complete(RAW))

fresh.post("/student/skills", data={"skills": [str(SKILL)]}, follow_redirects=True)
with app.app_context():
    step("adding a skill completes it", profiles.is_complete(RAW))
    step("and the moment is recorded",
         query("SELECT completed_at FROM student_profiles WHERE user_id=%s",
               (RAW,), one=True)["completed_at"] is not None)

r = fresh.get("/student/profile")
step("the page says so", b"Your profile is complete" in r.data)
step("and suggests what would help without demanding it",
     b"GitHub" in r.data)

r = fresh.post(f"/student/projects/{brief}/apply",
               data={"message": "I would like to build this because it fits my course."},
               follow_redirects=True)
step("the application now goes through",
     b"Finish your profile before applying" not in r.data)
with app.app_context():
    step("and is recorded",
         scalar("SELECT COUNT(*) FROM project_applications WHERE student_id=%s",
                (RAW,)) == 1)

# Emptying the profile again closes the gate.
fresh.post("/student/profile", data={"bio": "too short", "level": "400"},
           follow_redirects=True)
with app.app_context():
    step("gutting the profile closes it again", not profiles.is_complete(RAW))
    step("and the completion stamp is cleared",
         query("SELECT completed_at FROM student_profiles WHERE user_id=%s",
               (RAW,), one=True)["completed_at"] is None)

# A student placed by a lecturer is not gated — that is the lecturer's call.
with app.app_context():
    placed = query("""SELECT u.email FROM assignments a JOIN users u ON u.id=a.student_id
                       WHERE a.lecturer_id IS NOT NULL LIMIT 1""", one=True)
if placed:
    pc = login(placed["email"])
    step("a student already placed by a lecturer can still work",
         pc.get("/student/dashboard").status_code == 200)

print("\n--- proving email works ---\n")

INBOX.clear()
student = login("chidi@demo.marketplace")
r = student.get("/student/notifications")
step("the alerts page offers a test send", b"Send me a test email" in r.data)

r = student.post("/settings/test-email", follow_redirects=True)
step("the test is sent", b"Sent to chidi@demo.marketplace" in r.data, r.status_code)
step("and really arrived", len(INBOX) == 1, len(INBOX))
if INBOX:
    step("it says what it is", "test" in body_of(INBOX[0]).lower())

r = student.post("/settings/test-email", follow_redirects=True)
step("a second straight away is held back", b"Try again in" in r.data)

# With a local BASE_URL, a delivered email is still useless.
app.config["BASE_URL"] = "http://127.0.0.1:5000"
with student.session_transaction() as sess:
    sess["test_email_at"] = 0
r = student.post("/settings/test-email", follow_redirects=True)
step("a localhost site address is called out", b"links inside its emails" in r.data)
app.config["BASE_URL"] = "https://praxorax.test"

# And when the server refuses, say why rather than claiming success.
app.config["MAIL_HOST"] = "127.0.0.1"
app.config["MAIL_PORT"] = 9
with student.session_transaction() as sess:
    sess["test_email_at"] = 0
r = student.post("/settings/test-email", follow_redirects=True)
step("a refusal is reported, not swallowed", b"Could not send" in r.data)
app.config["MAIL_PORT"] = 8026

app.config["MAIL_ENABLED"] = False
with student.session_transaction() as sess:
    sess["test_email_at"] = 0
r = student.post("/settings/test-email", follow_redirects=True)
step("with email off, it says that plainly", b"MAIL_ENABLED" in r.data)
app.config["MAIL_ENABLED"] = True

# The empty list should explain itself rather than just saying "nothing".
empty = login("raw@v16.test", "password123")
r = empty.get("/student/notifications")
step("an empty alert list explains what would appear there",
     b"Alerts land here when something needs you" in r.data)

controller.stop()
print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
