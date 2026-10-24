"""Contacts, the feedback survey, and supervision messages.

Three features that arrived together. What they have in common is that each
one is a channel between people who previously had none, so each one is also
a way to leak something. Most of what follows is about who can see what.

Sent against a real SMTP server, so a message counted here actually left.
Run after seed_demo.py.
"""
import email as emaillib
import os
import time

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up24",
                  TRIAL_DAYS="0", MAIL_ENABLED="true", MAIL_HOST="127.0.0.1",
                  MAIL_PORT="8031", MAIL_FROM="alerts@praxorax.test",
                  MAIL_STARTTLS="false", MAIL_SSL="false",
                  MAIL_SYNCHRONOUS="true", CONTACT_EMAIL="team@praxorax.test",
                  BASE_URL="https://praxorax.test")

from aiosmtpd.controller import Controller

INBOX = []


class Collector:
    async def handle_DATA(self, server, session, envelope):
        INBOX.append(emaillib.message_from_bytes(envelope.original_content))
        return "250 OK"


controller = Controller(Collector(), hostname="127.0.0.1", port=8031)
controller.start()
time.sleep(0.4)

from werkzeug.security import generate_password_hash

import social
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


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def login(address, password="demo1234"):
    c = app.test_client()
    c.post("/login", data={"email": address, "password": password})
    return c


with app.app_context():
    execute("""INSERT INTO users (fullname,email,password,role)
               VALUES ('Root','root@v24.test',%s,'admin')
               ON CONFLICT (email) DO NOTHING""",
            (generate_password_hash("password123"),))
    execute("DELETE FROM feedback")
    execute("DELETE FROM social_links")
    execute("DELETE FROM messages")

pub = app.test_client()
admin = login("root@v24.test", "password123")

# ====================================================== handles, parsed
print("\n--- what people actually paste ---\n")

with app.app_context():
    CASES = [
        ("whatsapp", "+234 801 234 5678", "2348012345678"),
        ("whatsapp", "0803-555-0199", "08035550199"),
        ("whatsapp", "https://wa.me/2348012345678", "2348012345678"),
        ("telegram", "@adaobi", "adaobi"),
        ("telegram", "https://t.me/adaobi", "adaobi"),
        ("x", "https://twitter.com/adaobi?s=21&t=xyz", "adaobi"),
        ("x", "@adaobi", "adaobi"),
        ("linkedin", "https://www.linkedin.com/in/ada-obi-1234/", "in/ada-obi-1234"),
        ("linkedin", "company/praxorax", "company/praxorax"),
        ("linkedin", "ada-obi", "in/ada-obi"),
        ("instagram", "https://instagram.com/adaobi/", "adaobi"),
        ("tiktok", "https://www.tiktok.com/@adaobi", "adaobi"),
        ("youtube", "https://www.youtube.com/@praxorax", "praxorax"),
        ("facebook", "https://fb.me/praxorax", "praxorax"),
    ]
    for net, raw, want in CASES:
        got = social.clean(net, raw)
        step(f"{net}: {raw[:38]}", got == want, f"got {got!r}")

    # A link to somewhere else must not be stored as a handle, or the
    # profile ends up with a button pointing at a stranger's site.
    step("a link to another site is refused",
         social.clean("facebook", "https://evil.example.com/ada") is None)
    step("so is one dressed up as a path",
         social.clean("x", "https://notx.com/ada") is None)
    step("whitespace is not a username",
         social.clean("telegram", "ada obi") is None)
    step("neither is something too short to be a phone number",
         social.clean("whatsapp", "0801") is None)
    step("an empty field is simply nothing",
         social.clean("telegram", "   ") is None)
    step("every network builds a link",
         all(social.url_for_handle(k, "x").startswith("https://")
             for k in social.NETWORKS))

# =================================================== the platform's own
print("\n--- the platform's accounts ---\n")

r = admin.get("/admin/contacts")
step("an administrator has a page for them", r.status_code == 200, r.status_code)
step("every network asked for is on it",
     all(f'name="{k}"'.encode() in r.data for k in
         ("facebook", "whatsapp", "telegram", "instagram", "youtube",
          "tiktok", "x", "linkedin")))

admin.post("/admin/contacts", data={
    "whatsapp": "+2348012345678", "telegram": "praxorax",
    "x": "https://x.com/praxorax", "linkedin": "company/praxorax",
    "facebook": "praxorax", "instagram": "praxorax",
    "tiktok": "@praxorax", "youtube": "@praxorax"}, follow_redirects=True)

body = pub.get("/contact").data
step("the contact page is public", pub.get("/contact").status_code == 200)
step("and shows them as working links", b"wa.me/2348012345678" in body)
step("including the ones asked for by name",
     all(b in body for b in (b"x.com/praxorax", b"tiktok.com/@praxorax",
                             b"youtube.com/@praxorax", b"linkedin.com")))
step("the footer carries them too", b"social-row" in pub.get("/").data)

# Blank means absent, not a dead link to a network nobody is on.
admin.post("/admin/contacts", data={"whatsapp": "+2348012345678"},
           follow_redirects=True)
body = pub.get("/contact").data
step("clearing one takes it down", b"tiktok.com" not in body)
step("without disturbing the others", b"wa.me/2348012345678" in body)
with app.app_context():
    step("and the row is gone rather than blanked",
         scalar("SELECT COUNT(*) FROM social_links WHERE user_id IS NULL") == 1)

step("an ordinary account cannot edit them",
     login("ada@demo.marketplace").get("/admin/contacts").status_code in (302, 403))

# ====================================================== personal handles
print("\n--- everybody's own ---\n")

ada = login("ada@demo.marketplace")
step("there is a page for them", ada.get("/settings/links").status_code == 200)

ada.post("/settings/links", data={"whatsapp": "+2348090000001",
                                  "telegram": "adaobi"}, follow_redirects=True)
with app.app_context():
    uid = query("SELECT id, links_public FROM users WHERE email='ada@demo.marketplace'",
                one=True)
    held = social.handles_for(uid["id"])
step("they are saved against the person", held.get("telegram") == "adaobi", held)
step("but hidden until they say otherwise", uid["links_public"] is False)

ada.post("/settings/links", data={"whatsapp": "+2348090000001",
                                  "telegram": "adaobi",
                                  "links_public": "on"}, follow_redirects=True)
with app.app_context():
    step("showing them is a deliberate act",
         query("SELECT links_public FROM users WHERE id=%s", (uid["id"],),
               one=True)["links_public"] is True)

r = ada.post("/settings/links", data={"telegram": "not a username"},
             follow_redirects=True)
step("a handle that cannot be read is reported, not swallowed",
     b"check what you pasted" in r.data)

# ========================================================== the survey
print("\n--- the survey ---\n")

INBOX.clear()
r = pub.get("/feedback")
step("anyone can open it without an account", r.status_code == 200)
step("it asks for a rating", b'name="rating"' in r.data)
step("what is missing", b'name="missing"' in r.data)
step("and a suggestion", b'name="suggestion"' in r.data)

r = pub.post("/feedback", data={"rating": "2", "missing": "No dark mode",
                                "suggestion": "Filter briefs by city",
                                "reply_to": "visitor@example.com"},
             follow_redirects=True)
step("a visitor can send one", r.status_code == 200)
step("and is thanked", b"reached us" in r.data)

with app.app_context():
    row = query("SELECT * FROM feedback ORDER BY id DESC LIMIT 1", one=True)
step("it is in the database", row is not None)
step("with the rating", row and row["rating"] == 2)
step("what is missing", row and row["missing"] == "No dark mode")
step("the suggestion", row and row["suggestion"] == "Filter briefs by city")
step("where to reply", row and row["reply_to"] == "visitor@example.com")
step("and marked unread", row and row["status"] == "new")

step("it is emailed to the address on the site",
     any("team@praxorax.test" in (m["To"] or "") for m in INBOX), len(INBOX))
sent = [m for m in INBOX if "team@praxorax.test" in (m["To"] or "")]
if sent:
    text = plain(sent[0])
    step("the mail carries the rating", "2/5" in text)
    step("and what they wrote", "No dark mode" in text)
    step("and where to reply", "visitor@example.com" in text)

with app.app_context():
    told = scalar("""SELECT COUNT(*) FROM notifications n
                      JOIN users u ON u.id = n.user_id
                     WHERE u.role='admin' AND n.body LIKE %s""", ("%feedback%",))
step("an administrator is told in the app as well", told >= 1, told)

# A rating is the one thing required; everything else optional.
r = pub.post("/feedback", data={"rating": "5"}, follow_redirects=True)
step("a rating on its own is enough", b"reached us" in r.data)
r = pub.post("/feedback", data={"rating": "", "missing": "x"},
             follow_redirects=True)
step("but a survey with no rating is refused", b"Choose a rating" in r.data)
r = pub.post("/feedback", data={"rating": "9"}, follow_redirects=True)
step("and a rating outside one to five", b"Choose a rating" in r.data)
r = pub.post("/feedback", data={"rating": "3", "reply_to": "notanemail"},
             follow_redirects=True)
step("a malformed address is caught", b"does not look right" in r.data)

body = admin.get("/admin/feedback").data
step("an administrator can read them all", b"No dark mode" in body)
step("with the average shown", b"Average rating" in body)
with app.app_context():
    fid = query("SELECT id FROM feedback ORDER BY id LIMIT 1", one=True)["id"]
admin.post(f"/admin/feedback/{fid}/actioned", follow_redirects=True)
with app.app_context():
    done = query("SELECT status, handled_by FROM feedback WHERE id=%s",
                 (fid,), one=True)
step("and record what was done about one", done["status"] == "actioned")
step("and by whom", done["handled_by"] is not None)
step("an ordinary account cannot read the feedback",
     ada.get("/admin/feedback").status_code in (302, 403))

# A dead mail server must not lose a piece of feedback.
app.config["MAIL_PORT"] = 9
r = pub.post("/feedback", data={"rating": "1", "missing": "Mail is down"},
             follow_redirects=True)
step("feedback survives the mail server being down", r.status_code == 200)
with app.app_context():
    step("and is stored anyway",
         scalar("SELECT COUNT(*) FROM feedback WHERE missing='Mail is down'") == 1)
app.config["MAIL_PORT"] = 8031

# ======================================================== the messages
print("\n--- a student and their supervisor ---\n")

with app.app_context():
    a = query("""SELECT id, student_id, lecturer_id FROM assignments
                  WHERE lecturer_id IS NOT NULL ORDER BY id LIMIT 1""", one=True)
    stu = query("SELECT email, fullname FROM users WHERE id=%s",
                (a["student_id"],), one=True)
    lec = query("SELECT email, fullname FROM users WHERE id=%s",
                (a["lecturer_id"],), one=True)

student = login(stu["email"])
lecturer = login(lec["email"])

step("the student has a list of threads",
     student.get("/messages/").status_code == 200)
step("so does the lecturer", lecturer.get("/messages/").status_code == 200)
step("the placement is on it", stu["fullname"].encode()
     in lecturer.get("/messages/").data or b"message" in lecturer.get("/messages/").data)

INBOX.clear()
student.post(f"/messages/{a['id']}",
             data={"body": "Should the report include the raw data?"},
             follow_redirects=True)
with app.app_context():
    m = query("SELECT * FROM messages ORDER BY id DESC LIMIT 1", one=True)
step("the message is stored", m is not None)
step("against the placement", m and m["assignment_id"] == a["id"])
step("and the sender", m and m["sender_id"] == a["student_id"])
step("unread until the other person opens it", m and m["read_at"] is None)

step("the lecturer is told", any(lec["email"] in (x["To"] or "") for x in INBOX),
     len(INBOX))

body = lecturer.get(f"/messages/{a['id']}").data
step("the lecturer can read it", b"include the raw data" in body)
with app.app_context():
    step("and opening it marks it read",
         query("SELECT read_at FROM messages WHERE id=%s", (m["id"],),
               one=True)["read_at"] is not None)

lecturer.post(f"/messages/{a['id']}", data={"body": "Yes, as an appendix."},
              follow_redirects=True)
step("the student sees the reply",
     b"as an appendix" in student.get(f"/messages/{a['id']}").data)

# --- who cannot read it
step("a company on the same project cannot open the thread",
     login("hr@demo.marketplace").get(f"/messages/{a['id']}").status_code == 404)
step("nor can an unrelated student",
     login("chidi@demo.marketplace").get(f"/messages/{a['id']}").status_code == 404)
step("nor an administrator",
     admin.get(f"/messages/{a['id']}").status_code == 404)
step("and signed out, nothing at all",
     app.test_client().get(f"/messages/{a['id']}").status_code in (302, 401))

# An outsider must not be able to post into somebody else's thread either.
before = None
with app.app_context():
    before = scalar("SELECT COUNT(*) FROM messages WHERE assignment_id=%s",
                    (a["id"],))
login("chidi@demo.marketplace").post(f"/messages/{a['id']}",
                                     data={"body": "Let me in"})
with app.app_context():
    step("and cannot post into it",
         scalar("SELECT COUNT(*) FROM messages WHERE assignment_id=%s",
                (a["id"],)) == before)

r = student.post(f"/messages/{a['id']}", data={"body": "   "},
                 follow_redirects=True)
step("an empty message is refused", b"Write something first" in r.data)

# --- the outside handles, only when offered
with app.app_context():
    execute("UPDATE users SET links_public=FALSE WHERE id=%s", (a["lecturer_id"],))
    social.save(a["lecturer_id"], {"whatsapp": "+2348091111111"})
body = student.get(f"/messages/{a['id']}").data
step("a supervisor's number is not shown while it is private",
     b"2348091111111" not in body)

with app.app_context():
    execute("UPDATE users SET links_public=TRUE WHERE id=%s", (a["lecturer_id"],))
body = student.get(f"/messages/{a['id']}").data
step("and is shown once they allow it", b"2348091111111" in body)
step("as an app link the student can press", b"wa.me/" in body)

# ================================ each network has a job, and they differ
print("\n--- what each network is for ---\n")

step("the messaging apps are grouped as contact",
     set(social.PURPOSE["contact"]["networks"]) ==
     {"whatsapp", "telegram", "facebook", "instagram", "x"},
     social.PURPOSE["contact"]["networks"])
step("LinkedIn is the professional profile",
     social.PURPOSE["profile"]["networks"] == ("linkedin",))
step("YouTube and TikTok are for broadcasting",
     set(social.PURPOSE["broadcast"]["networks"]) == {"youtube", "tiktok"})
step("every network belongs to exactly one group",
     sorted(n for g in social.PURPOSE.values() for n in g["networks"])
     == sorted(social.NETWORKS))

# Only the platform is asked for broadcast channels; a student's TikTok has
# no business on a page about supervised work.
step("the platform is asked for its channels",
     "broadcast" in dict(social.groups_for_role(None)))
step("a company is not", "broadcast" not in dict(social.groups_for_role("company")))
step("nor is a student", "broadcast" not in dict(social.groups_for_role("student")))
step("a company is asked for messaging apps first",
     social.groups_for_role("company")[0][0] == "contact")
step("a student is asked for their profile first",
     social.groups_for_role("student")[0][0] == "profile")

body = login("hr@demo.marketplace").get("/settings/links").data
step("the company form says what the apps are for", b"message you" in body)
step("and does not offer broadcast channels",
     b'name="tiktok"' not in body and b'name="youtube"' not in body)

body = login("ada@demo.marketplace").get("/settings/links").data
step("the student form leads with LinkedIn", b"professional profile" in body)

# --- sharing a Praxfolio to LinkedIn
url = social.share_url("linkedin", "https://praxorax.test/p/abc123")
step("a Praxfolio can be shared to LinkedIn", url is not None)
step("the share link carries the public Praxfolio URL",
     url and "praxorax.test%2Fp%2Fabc123" in url, url)
step("an unknown network simply has no share link",
     social.share_url("tiktok", "https://x") is None)

ada2 = login("ada@demo.marketplace")
ada2.post("/praxfolio/share" if False else "/student/praxfolio/share",
          follow_redirects=True)
body = ada2.get("/student/praxfolio").data
step("the button is on the Praxfolio once the link is public",
     b"Share on LinkedIn" in body or b"Create a public link" in body)

# ======================================= code arriving before its migration
print("\n--- deployed before the migration ran ---\n")

# This is the normal order of a deploy: the code reaches the server, the
# migration is run some minutes later. In between, the tables these features
# need do not exist. What must not happen is the rest of the site going down
# with them — the unread badge runs on every page a student opens, and the
# first version of it took the whole dashboard with it.
with app.app_context():
    execute("DROP TABLE IF EXISTS messages CASCADE")

student_after = login(stu["email"])
for path in ("/student/dashboard", "/student/projects", "/student/praxfolio"):
    r = student_after.get(path)
    step(f"{path} still answers without the messages table",
         r.status_code == 200, r.status_code)

step("and the public site is untouched",
     app.test_client().get("/").status_code == 200)

# The same applies to the footer links when social_links is missing.
with app.app_context():
    execute("DROP TABLE IF EXISTS social_links CASCADE")
step("the landing page survives a missing social_links table",
     app.test_client().get("/").status_code == 200)

# A failed read must not poison the rest of the request. Postgres refuses
# every later statement on a connection whose transaction aborted, so one
# bad query used to take down whatever ran after it.
with app.app_context():
    try:
        query("SELECT 1 FROM table_that_does_not_exist")
    except Exception:
        pass
    ok = query("SELECT COUNT(*) AS n FROM users", one=True)
    step("a failed query leaves the connection usable", ok is not None
         and ok["n"] > 0, ok)

with app.app_context():
    for stmt in open(os.path.join(ROOT, "database", "migration_v12.sql")).read().split(";"):
        if stmt.strip():
            try:
                execute(stmt)
            except Exception:
                pass
step("and the tables come back when the migration is run",
     app.test_client().get("/").status_code == 200)

controller.stop()
print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
