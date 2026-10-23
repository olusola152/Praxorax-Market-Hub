"""Inviting a stranger: the page, the signup, the seat on the team.

The invitation email used to drop somebody who had never heard of the site
straight onto a signup form, and landed them as 'invited' afterwards so they
had to say yes a second time. This covers the replacement: a public page that
explains the place first, and a signup through that page that puts them on
the team outright.

Runs against a real SMTP server so a message counted here is one that left.
"""
import email as emaillib
import os
import re
import time

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up19",
                  TRIAL_DAYS="0", MAIL_ENABLED="true", MAIL_HOST="127.0.0.1",
                  MAIL_PORT="8029", MAIL_FROM="alerts@praxorax.test",
                  MAIL_STARTTLS="false", MAIL_SSL="false",
                  MAIL_SYNCHRONOUS="true", BASE_URL="https://praxorax.test")

from aiosmtpd.controller import Controller

INBOX = []


class Collector:
    async def handle_DATA(self, server, session, envelope):
        INBOX.append(emaillib.message_from_bytes(envelope.original_content))
        return "250 OK"


controller = Controller(Collector(), hostname="127.0.0.1", port=8029)
controller.start()
time.sleep(0.4)

import invitations
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


def login(address, password="demo1234"):
    c = app.test_client()
    c.post("/login", data={"email": address, "password": password})
    return c


with app.app_context():
    for addr in ("stranger@v19.test", "already@v19.test", "second@v19.test"):
        execute("DELETE FROM users WHERE email=%s", (addr,))
    execute("DELETE FROM team_invitations WHERE email LIKE %s", ("%@v19.test",))
    FIELD = query("SELECT id FROM fields LIMIT 1", one=True)["id"]

# ------------------------------------------------- a lead invites a stranger
print("\n--- the invitation goes out ---\n")

lead = login("ada@demo.marketplace")
lead.post("/teams/new", data={"name": "Bridge Team"}, follow_redirects=True)
with app.app_context():
    TEAM = query("SELECT id FROM teams WHERE name='Bridge Team' ORDER BY id DESC",
                 one=True)["id"]

INBOX.clear()
lead.post(f"/teams/{TEAM}/invite", data={"email": "stranger@v19.test"},
          follow_redirects=True)

to_them = [m for m in INBOX if "stranger@v19.test" in (m["To"] or "")]
step("the stranger is emailed", len(to_them) == 1, len(INBOX))

TOKEN = None
if to_them:
    body = plain(to_them[0])
    step("the email explains what the place is",
         "companies post work" in body.lower())
    step("and that a lecturer reviews the work", "lecturer reviews" in body)
    step("and that students never pay", "nothing to pay" in body)

    found = re.search(r"https://praxorax\.test(/invite/[A-Za-z0-9_-]+)", body)
    step("it links to the invitation page, not the signup form", bool(found),
         body[-200:] if not found else found.group(1))
    if found:
        TOKEN = found.group(1).rsplit("/", 1)[1]
    step("the signup form is not linked directly",
         "/register?invite=" not in body)

with app.app_context():
    row = query("SELECT token FROM team_invitations WHERE email=%s",
                ("stranger@v19.test",), one=True)
    step("an invitation row was written", bool(row))
    if row and not TOKEN:
        TOKEN = row["token"]
    step("the emailed token is the stored one", row and TOKEN == row["token"])

# ------------------------------------------------------- the landing page
print("\n--- what the stranger sees ---\n")

visitor = app.test_client()
r = visitor.get(f"/invite/{TOKEN}")
page = r.data.decode()
step("the page opens with no account and no sign-in", r.status_code == 200,
     r.status_code)
step("it names who invited them", "Ada Obi" in page)
step("and the team", "Bridge Team" in page)
step("it says what the platform does",
     "Real briefs posted by real companies" in page)
step("it says a lecturer supervises", "lecturer reviews the work" in page)
step("it says students never pay", "Students never pay" in page)
step("it offers to create the account and join in one go",
     "Create my account and join" in page)
step("the button carries the token", f"invite={TOKEN}" in page)
step("it does not ask for a password on this page",
     'type="password"' not in page)

# ------------------------------------------- signing up through that link
print("\n--- they sign up from the invitation ---\n")

INBOX.clear()
r = visitor.post(f"/register?invite={TOKEN}",
                 data={"role": "student", "fullname": "Stray Visitor",
                       "email": "stranger@v19.test", "password": "password123",
                       "confirm": "password123", "field_id": str(FIELD)},
                 follow_redirects=True)
step("the account is created", r.status_code == 200, r.status_code)

with app.app_context():
    new_user = query("SELECT id, fullname FROM users WHERE email=%s",
                     ("stranger@v19.test",), one=True)
    step("the user row exists", bool(new_user))
    seat = query("""SELECT status, joined_at FROM team_members
                     WHERE team_id=%s AND user_id=%s""",
                 (TEAM, new_user["id"]), one=True) if new_user else None

step("they are on the team", bool(seat))
step("as an active member, not another pending invitation",
     seat and seat["status"] == "active", seat and seat["status"])
step("and the join is dated", seat and seat["joined_at"] is not None)

with app.app_context():
    inv = query("SELECT status, accepted_by FROM team_invitations WHERE token=%s",
                (TOKEN,), one=True)
step("the invitation is marked accepted", inv and inv["status"] == "accepted")
step("by them", inv and new_user and inv["accepted_by"] == new_user["id"])

step("they land on the team page, not a list of things to accept",
     "Bridge Team" in r.data.decode())
step("and are told they are on it", b"You are on" in r.data)

# the two emails this has to produce
step("the new member is welcomed",
     any("stranger@v19.test" in (m["To"] or "") for m in INBOX), len(INBOX))
to_lead = [m for m in INBOX if "ada@demo.marketplace" in (m["To"] or "")]
step("and the lead is told they joined", len(to_lead) >= 1, len(INBOX))
if to_lead:
    joined_note = [m for m in to_lead if "joined" in plain(m)]
    step("in those words, not 'waiting to accept'", bool(joined_note),
         plain(to_lead[0])[:90])

# the link is spent
r = visitor.get(f"/invite/{TOKEN}")
step("the link cannot be used twice", r.status_code == 410, r.status_code)
step("and says so plainly", b"already been used" in r.data)

# ------------------------------------------ a second, unfollowed invitation
print("\n--- an invitation they did not follow ---\n")

# Invited to a second team, but signing up via the FIRST team's link. Only
# the followed one is consent; the other has to wait to be accepted.
with app.app_context():
    execute("DELETE FROM users WHERE email=%s", ("second@v19.test",))
lead.post("/teams/new", data={"name": "Other Team"}, follow_redirects=True)
with app.app_context():
    TEAM2 = query("SELECT id FROM teams WHERE name='Other Team' ORDER BY id DESC",
                  one=True)["id"]

lead.post(f"/teams/{TEAM}/invite", data={"email": "second@v19.test"},
          follow_redirects=True)
lead.post(f"/teams/{TEAM2}/invite", data={"email": "second@v19.test"},
          follow_redirects=True)
with app.app_context():
    t1 = query("SELECT token FROM team_invitations WHERE email=%s AND team_id=%s",
               ("second@v19.test", TEAM), one=True)["token"]

two = app.test_client()
two.post(f"/register?invite={t1}",
         data={"role": "student", "fullname": "Two Teams",
               "email": "second@v19.test", "password": "password123",
               "confirm": "password123", "field_id": str(FIELD)},
         follow_redirects=True)

with app.app_context():
    uid = query("SELECT id FROM users WHERE email=%s",
                ("second@v19.test",), one=True)["id"]
    a = query("SELECT status FROM team_members WHERE team_id=%s AND user_id=%s",
              (TEAM, uid), one=True)
    b = query("SELECT status FROM team_members WHERE team_id=%s AND user_id=%s",
              (TEAM2, uid), one=True)
step("the team whose link they followed takes them in",
     a and a["status"] == "active", a and a["status"])
step("the one they never saw stays an invitation",
     b and b["status"] == "invited", b and b["status"])

# ------------------------------------------- an address that already exists
print("\n--- the address turns out to be registered ---\n")

with app.app_context():
    execute("DELETE FROM team_invitations WHERE email=%s", ("chidi@demo.marketplace",))
    execute("""DELETE FROM team_members WHERE team_id=%s AND user_id=(
                 SELECT id FROM users WHERE email='chidi@demo.marketplace')""",
            (TEAM2,))
    row = invitations.invite_email(TEAM2, "chidi@demo.marketplace",
                                   query("SELECT id FROM users WHERE email='ada@demo.marketplace'",
                                         one=True)["id"])
    T3 = row["token"]

anon = app.test_client()
r = anon.get(f"/invite/{T3}")
step("a registered address is offered sign-in, not signup",
     b"already have an account" in r.data, r.status_code)
step("and not asked to create one",
     b"Create my account and join" not in r.data)

# signed in as the wrong person
wrong = login("ada@demo.marketplace")
r = wrong.get(f"/invite/{T3}")
step("the wrong signed-in person is told so", b"somebody else" in r.data)
r = wrong.post(f"/invite/{T3}/join", follow_redirects=True)
with app.app_context():
    stolen = query("""SELECT 1 FROM team_members WHERE team_id=%s AND user_id=(
                        SELECT id FROM users WHERE email='ada@demo.marketplace')
                        AND status='active' AND joined_at IS NOT NULL""",
                   (TEAM2,), one=True)
step("and cannot spend a token sent to another address",
     b"was sent to" in r.data)

# the right person
INBOX.clear()
right = login("chidi@demo.marketplace")
r = right.post(f"/invite/{T3}/join", follow_redirects=True)
with app.app_context():
    uid = query("SELECT id FROM users WHERE email='chidi@demo.marketplace'",
                one=True)["id"]
    seat = query("SELECT status FROM team_members WHERE team_id=%s AND user_id=%s",
                 (TEAM2, uid), one=True)
step("the invited person joins in one click", seat and seat["status"] == "active",
     seat and seat["status"])
step("the lead is emailed about it",
     any("ada@demo.marketplace" in (m["To"] or "") for m in INBOX), len(INBOX))
step("and the joiner gets their own confirmation",
     any("chidi@demo.marketplace" in (m["To"] or "") for m in INBOX))

# --------------------------------------------------------- dead links
print("\n--- links that should not work ---\n")

r = app.test_client().get("/invite/not-a-real-token")
step("an unknown token is not a crash", r.status_code == 404, r.status_code)
step("and explains itself", b"not one we recognise" in r.data)

with app.app_context():
    row = invitations.invite_email(TEAM2, "expired@v19.test",
                                   query("SELECT id FROM users WHERE email='ada@demo.marketplace'",
                                         one=True)["id"])
    execute("UPDATE team_invitations SET expires_at = NOW() - INTERVAL '1 day' "
            "WHERE id=%s", (row["id"],))
r = app.test_client().get(f"/invite/{row['token']}")
step("an expired invitation is closed", r.status_code == 410, r.status_code)
step("and says it expired", b"has expired" in r.data)
step("but still offers a way in", b"Create a student account" in r.data)

with app.app_context():
    row = invitations.invite_email(TEAM2, "withdrawn@v19.test",
                                   query("SELECT id FROM users WHERE email='ada@demo.marketplace'",
                                         one=True)["id"])
    execute("UPDATE team_invitations SET status='cancelled' WHERE id=%s",
            (row["id"],))
r = app.test_client().get(f"/invite/{row['token']}")
step("a withdrawn invitation is closed", r.status_code == 410)
step("and says who withdrew it", b"withdrawn by the person who sent it" in r.data)

# ------------------------------------------------------- the team ceiling
print("\n--- a full team ---\n")

with app.app_context():
    boss = query("SELECT id FROM users WHERE email='ada@demo.marketplace'",
                 one=True)["id"]
    execute("""INSERT INTO teams (name, created_by, status)
               VALUES ('Full Team', %s, 'forming')""", (boss,))
    FULL = query("SELECT id FROM teams WHERE name='Full Team' ORDER BY id DESC",
                 one=True)["id"]
    others = query("SELECT id FROM users WHERE role='student' LIMIT %s",
                   (invitations.MAX_MEMBERS,))
    for o in others:
        execute("""INSERT INTO team_members (team_id, user_id, status)
                   VALUES (%s,%s,'active')
                   ON CONFLICT (team_id, user_id) DO NOTHING""",
                (FULL, o["id"]))
    row = invitations.invite_email(FULL, "late@v19.test", boss)
    seats = scalar("""SELECT COUNT(*) FROM team_members WHERE team_id=%s
                       AND status IN ('active','invited')""", (FULL,))

step("the team is at capacity", seats >= invitations.MAX_MEMBERS, seats)
r = app.test_client().get(f"/invite/{row['token']}")
step("a latecomer is told the team is full", b"is full" in r.data, r.status_code)
step("and is not offered the join button",
     b"Create my account and join" not in r.data)

controller.stop()
print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
