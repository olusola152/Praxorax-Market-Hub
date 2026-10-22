"""Verifying an institution. Run after seed_demo.py.

A university registering used to get a live public portal at /u/<slug>
immediately. Anyone could register as a real institution and collect lecturer
and student signups — including matriculation numbers — under its name. A
company has needed an administrator's approval since v4; an institution now
clears the same bar.
"""
import os

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up17",
                  TRIAL_DAYS="0", IDLE_TIMEOUT_MINUTES="20")

from werkzeug.security import generate_password_hash

from app import app
from db import execute, query, scalar

app.config["TESTING"] = True
P = F = 0

NAME = "Checkworthy Polytechnic"
EMAIL = "registrar@checkworthy.test"


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


def uni_row():
    with app.app_context():
        return query("SELECT * FROM universities WHERE name=%s", (NAME,), one=True)


with app.app_context():
    execute("DELETE FROM users WHERE email=%s", (EMAIL,))
    execute("DELETE FROM universities WHERE name=%s", (NAME,))
    execute("""INSERT INTO users (fullname, email, password, role)
               VALUES ('Root','root@v17.test',%s,'admin')
               ON CONFLICT (email) DO NOTHING""",
            (generate_password_hash("password123"),))

admin = app.test_client()
admin.post("/login", data={"email": "root@v17.test", "password": "password123"})

# ------------------------------------------------------------ registering
reg = app.test_client()
r = reg.post("/register",
             data={"role": "university", "fullname": "The Registrar",
                   "email": EMAIL, "password": "password123",
                   "confirm": "password123", "university_name": NAME,
                   "city": "Lagos"},
             follow_redirects=True)
step("an institution can still register", r.status_code == 200)
step("and is told it will be checked", b"we confirm the" in r.data)
step("and asked for something to check", b"Confirm your institution" in r.data)

uni = uni_row()
step("it starts unverified", uni["verification_status"] == "pending",
     uni["verification_status"])
step("nothing is auto-approved on the way in", uni["verified_at"] is None)

with app.app_context():
    told = scalar("""SELECT COUNT(*) FROM notifications n
                      JOIN users u ON u.id = n.user_id
                     WHERE u.role='admin' AND n.body LIKE %s""",
                  ("%registered as an institution%",))
step("an administrator is told there is something to do", told >= 1, told)

# ------------------------------------------------------- the portal is shut
anon = app.test_client()
r = anon.get(f"/u/{uni['slug']}")
step("the portal page still resolves", r.status_code == 200)
step("but says it is not open yet", b"not open for registration yet" in r.data)
step("and does not blame a subscription",
     b"subscription has" not in r.data)

r = anon.get(f"/u/{uni['slug']}/student")
step("students cannot sign up through it", b"Registration is closed" in r.data)
r = anon.get(f"/u/{uni['slug']}/lecturer")
step("nor can lecturers", b"Registration is closed" in r.data)

# Forcing the POST must fail too, not just the form being hidden.
with app.app_context():
    field = query("SELECT id FROM fields LIMIT 1", one=True)["id"]
r = anon.post(f"/u/{uni['slug']}/student",
              data={"fullname": "Sneaky Student", "email": "sneak@v17.test",
                    "password": "password123", "confirm": "password123",
                    "field_id": str(field)}, follow_redirects=True)
with app.app_context():
    step("and posting straight at it creates nobody",
         scalar("SELECT COUNT(*) FROM users WHERE email='sneak@v17.test'") == 0)

# ------------------------------------------------------ and so are passcodes
r = reg.post("/university/passcodes", data={"faculty": "Science", "count": "2"},
             follow_redirects=True)
step("lecturer codes cannot be issued yet",
     b"has not been verified yet" in r.data)
with app.app_context():
    step("and none were made",
         scalar("SELECT COUNT(*) FROM passcodes WHERE university_id=%s",
                (uni["id"],)) == 0)

# The rest of their account still works — this is a gate, not a suspension.
step("the dashboard is still theirs to use",
     reg.get("/university/dashboard").status_code == 200)

# ---------------------------------------------------------- sending evidence
r = reg.post("/university/verification", data={"evidence_url": "not-a-url"},
             follow_redirects=True)
step("a bare word is not a link", b"full web address" in r.data)
r = reg.post("/university/verification",
             data={"evidence_url": "", "evidence_note": "trust me"},
             follow_redirects=True)
step("and neither is a one-liner with no link", b"explain in a sentence" in r.data)

r = reg.post("/university/verification",
             data={"evidence_url": "https://checkworthy.edu.ng/about",
                   "evidence_note": "Our accreditation page."},
             follow_redirects=True)
step("a real link is accepted", b"An administrator will look at it" in r.data)
uni = uni_row()
step("it is recorded", uni["evidence_url"] == "https://checkworthy.edu.ng/about")
step("with the time it arrived", uni["evidence_submitted_at"] is not None)
step("the institution is still not verified by sending it",
     uni["verification_status"] == "pending")

r = reg.get("/university/dashboard")
step("and the dashboard says it is with an administrator",
     b"with an administrator" in r.data)

# ------------------------------------------------------------- the decision
r = admin.get("/admin/kyc")
step("it appears in the administrator's queue", NAME.encode() in r.data)
step("with the evidence to open", b"checkworthy.edu.ng" in r.data)
step("and what is at stake", b"/u/" + uni["slug"].encode() in r.data)

r = admin.get("/admin/dashboard")
step("the deck counts it as waiting on a decision",
     b"Verification waiting" in r.data)

r = admin.post(f"/admin/universities/{uni['id']}/reject", data={"notes": "no"},
               follow_redirects=True)
step("a rejection without a real reason is refused", b"Say why" in r.data)
step("so it is still pending", uni_row()["verification_status"] == "pending")

r = admin.post(f"/admin/universities/{uni['id']}/reject",
               data={"notes": "Nothing on that page links you to the institution."},
               follow_redirects=True)
uni = uni_row()
step("a reasoned rejection sticks", uni["verification_status"] == "rejected")
step("the reason is kept", "Nothing on that page" in (uni["verification_notes"] or ""))
step("and who decided", uni["verified_by"] is not None)

with app.app_context():
    uid = query("SELECT admin_user_id FROM universities WHERE id=%s",
                (uni["id"],), one=True)["admin_user_id"]
    said = scalar("SELECT COUNT(*) FROM notifications WHERE user_id=%s AND body LIKE %s",
                  (uid, "%could not confirm%"))
step("the institution is told why", said >= 1, said)

r = reg.get("/university/dashboard")
step("their dashboard shows the refusal", b"was not accepted" in r.data)
step("and what was said", b"Nothing on that page" in r.data)

r = reg.post("/university/verification",
             data={"evidence_url": "https://checkworthy.edu.ng/registrar",
                   "evidence_note": "Registrar's page, with my name on it."},
             follow_redirects=True)
step("sending something else puts them back in the queue",
     uni_row()["verification_status"] == "pending")

r = admin.post(f"/admin/universities/{uni['id']}/verify", data={},
               follow_redirects=True)
uni = uni_row()
step("verifying needs no reason", uni["verification_status"] == "verified")
step("and is timestamped", uni["verified_at"] is not None)

with app.app_context():
    said = scalar("SELECT COUNT(*) FROM notifications WHERE user_id=%s AND body LIKE %s",
                  (uid, "%has been verified%"))
step("the institution is told it is through", said >= 1, said)

# -------------------------------------------------------------- now it works
# Verification and subscription are separate gates and both have to be clear.
# Being verified alone does not open the portal, which is the point of having
# two: a paid-up institution nobody has checked is still unchecked, and a
# verified one that has not paid is still unpaid.
r = anon.get(f"/u/{uni['slug']}/student")
step("verified but unpaid, the portal is still shut",
     b"Registration is closed" in r.data)
r = anon.get(f"/u/{uni['slug']}")
step("and now it is the subscription being named, not the check",
     b"subscription has" in r.data and b"not open for registration yet" not in r.data)

# While verified but unpaid, passcodes are refused on the subscription —
# a different gate with a different message.
r = reg.post("/university/passcodes", data={"faculty": "Science", "count": "2"},
             follow_redirects=True)
step("and passcodes are refused on the subscription instead",
     b"Activate your subscription" in r.data)

with app.app_context():
    execute("""UPDATE universities SET subscription_status='active',
                      subscribed_until = CURRENT_DATE + 365 WHERE id=%s""",
            (uni["id"],))
r = anon.get(f"/u/{uni['slug']}/student")
step("with both gates clear, students can sign up",
     b"Registration is closed" not in r.data)
r = anon.get(f"/u/{uni['slug']}")
step("and the portal reads normally", b"not open for registration yet" not in r.data)

r = reg.post("/university/passcodes", data={"faculty": "Science", "count": "2"},
             follow_redirects=True)
step("the verification block on passcodes is gone",
     b"has not been verified yet" not in r.data)
with app.app_context():
    step("and codes really are issued now",
         scalar("SELECT COUNT(*) FROM passcodes WHERE university_id=%s",
                (uni["id"],)) == 2)

# ------------------------------------------------- institutions already here
# The migration grandfathers every institution that existed when it ran, so
# turning this on does not shut portals that were working yesterday.
with app.app_context():
    execute("""INSERT INTO universities (name, slug, city, subscription_status)
               VALUES ('Legacy Institute','legacy-institute','Ibadan','active')
               ON CONFLICT (name) DO NOTHING""")
    execute("""UPDATE universities SET verification_status='pending',
                      created_at = NOW() - INTERVAL '30 days'
                WHERE name='Legacy Institute'""")
    execute(open("database/migration_v11.sql").read())
    legacy = query("SELECT verification_status FROM universities WHERE name=%s",
                   ("Legacy Institute",), one=True)
step("re-running the migration grandfathers what was already here",
     legacy and legacy["verification_status"] == "verified", legacy)
step("and does not reach back over a deliberate rejection",
     uni_row()["verification_status"] == "verified")

print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
