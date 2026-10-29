"""Employer feedback: who may write it, who may see it, and what it averages.

The feature's whole value is that the rating is not self-reported, so most
of what matters here is refusal: a company rating somebody else's student, a
company rating work it has not approved, a student editing what was said
about them or publishing somebody else's feedback. Each of those is a test.

Run after seed_demo.py.
"""
import os

os.environ.setdefault("DATABASE_URL",
                      "postgresql://smtest:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up26",
                  TRIAL_DAYS="0", BASE_URL="https://praxorax.test")

import employer_feedback as ef
from app import app
from db import execute, query, scalar

app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


def login(address, password="demo1234"):
    """A signed-in client, or a loud failure.

    Worth asserting rather than assuming: a client that silently failed to
    sign in is redirected to /login by every route, which looks exactly like
    an authorisation check working and makes a permission test pass while
    proving nothing.
    """
    c = app.test_client()
    c.post("/login", data={"email": address, "password": password})
    with c.session_transaction() as s:
        assert s.get("user_id"), f"could not sign in as {address}"
    return c


GOOD = {"communication": "5", "problem_solving": "4", "quality": "4",
        "professionalism": "5",
        "comment": "Rebuilt our stock report and explained the numbers to "
                   "the warehouse team without being asked to."}

with app.app_context():
    placement = query(
        """SELECT a.id, a.student_id, p.id AS project_id, p.company_id,
                  cu.email AS company_email, su.email AS student_email
             FROM assignments a
             JOIN projects p ON p.id = a.project_id
             JOIN companies c ON c.id = p.company_id
             JOIN users cu ON cu.id = c.user_id
             JOIN users su ON su.id = a.student_id
            ORDER BY a.id LIMIT 1""", one=True)

    # The feature only exists for finished work, so make this one finished.
    execute("""UPDATE assignments SET status='completed', completed_at=NOW()
                WHERE id=%s""", (placement["id"],))
    execute("DELETE FROM employer_feedback WHERE assignment_id=%s",
            (placement["id"],))

    # Demo accounts only. Other suites leave behind companies and students
    # whose passwords this test does not know, and a client that cannot sign
    # in is redirected by every route — which would make the permission
    # checks below pass without ever reaching them.
    other_student = query(
        """SELECT id, email FROM users
            WHERE role='student' AND id <> %s AND email LIKE %s
            ORDER BY id LIMIT 1""",
        (placement["student_id"], "%demo.marketplace"), one=True)
    other_company = query(
        """SELECT u.email FROM companies c JOIN users u ON u.id = c.user_id
            WHERE c.id <> %s AND u.email LIKE %s
            ORDER BY c.id LIMIT 1""",
        (placement["company_id"], "%demo.marketplace"), one=True)

A = placement["id"]

# ------------------------------------------------------------ the schema
print("\n--- the table ---\n")

def refused(sql, params):
    """True when the database rejects this statement.

    The point of the CHECK constraints is that they hold even when the write
    does not come through parse() — a migration, a console, a future route.
    """
    try:
        with app.app_context():
            execute(sql, params)
        return False
    except Exception:
        return True


with app.app_context():
    step("employer_feedback exists",
         scalar("SELECT to_regclass('employer_feedback') IS NOT NULL"))

INSERT = """INSERT INTO employer_feedback
                (assignment_id, communication, problem_solving, quality,
                 professionalism) VALUES (%s,%s,1,1,1)"""
step("a score above five is refused by the database", refused(INSERT, (A, 9)))
step("and a score below one", refused(INSERT, (A, 0)))
step("feedback against no placement is refused",
     refused(INSERT, (99999999, 3)))

with app.app_context():
    execute("DELETE FROM employer_feedback WHERE assignment_id=%s", (A,))

# ------------------------------------------------------------- validation
print("\n--- what the form accepts ---\n")

scores, comment, errors = ef.parse(GOOD)
step("a complete form parses", not errors, errors)
step("and keeps every score", scores ==
     {"communication": 5, "problem_solving": 4, "quality": 4,
      "professionalism": 5}, scores)

_, _, errors = ef.parse({**GOOD, "quality": "6"})
step("a score above five is refused", any("1 to 5" in e for e in errors))

_, _, errors = ef.parse({**GOOD, "quality": ""})
step("a missing score is refused", any("quality" in e.lower() for e in errors))

_, _, errors = ef.parse({**GOOD, "comment": "good"})
step("a one-word comment is refused", any("at least" in e for e in errors))
step("and the refusal says why it matters",
     any("tell" in e or "nothing" in e for e in errors))

# --------------------------------------------------------- who may write
print("\n--- who may rate ---\n")

company = login(placement["company_email"])
r = company.post(f"/company/placements/{A}/feedback", data=GOOD,
                 follow_redirects=True)
step("the commissioning company can rate the student", r.status_code == 200,
     r.status_code)

with app.app_context():
    saved = ef.for_assignment(A)
step("the feedback is stored", bool(saved))
step("with the scores given", saved and saved["communication"] == 5
     and saved["quality"] == 4)
step("the average is computed by the database, not the template",
     saved and float(saved["overall"]) == 4.5, saved and saved["overall"])
step("and it starts hidden from the public link",
     saved and saved["is_public"] is False)

if other_company:
    r = login(other_company["email"]).post(
        f"/company/placements/{A}/feedback", data=GOOD)
    step("another company cannot rate this placement", r.status_code == 404,
         r.status_code)

r = login(placement["student_email"]).post(
    f"/company/placements/{A}/feedback", data=GOOD)
step("a student cannot reach the company's rating form",
     r.status_code in (302, 403, 404), r.status_code)
with app.app_context():
    step("and nothing they sent was stored",
         ef.for_assignment(A)["communication"] == 5)

# Rating work that is not finished.
with app.app_context():
    execute("UPDATE assignments SET status='in_progress' WHERE id=%s", (A,))
r = login(placement["company_email"]).post(
    f"/company/placements/{A}/feedback", data=GOOD, follow_redirects=True)
step("work that is not approved cannot be rated",
     "once the work is approved" in r.data.decode())
with app.app_context():
    execute("UPDATE assignments SET status='completed' WHERE id=%s", (A,))

# ------------------------------------------------------------ one per job
print("\n--- one rating per placement ---\n")

company.post(f"/company/placements/{A}/feedback",
             data={**GOOD, "quality": "2"}, follow_redirects=True)
with app.app_context():
    step("submitting again replaces rather than duplicates",
         scalar("SELECT COUNT(*) FROM employer_feedback WHERE assignment_id=%s",
                (A,)) == 1)
    again = ef.for_assignment(A)
    step("and the new score is the one kept", again["quality"] == 2)
    step("the average moves with it", float(again["overall"]) == 4.0,
         again["overall"])

# --------------------------------------------------------- who may see it
print("\n--- who may see it ---\n")

student = login(placement["student_email"])
page = student.get("/student/praxfolio").data.decode()
step("the student sees feedback written about them",
     "Employer verified feedback" in page)
step("and is told it is private so far", "Only you can see this" in page)

with app.app_context():
    token = scalar("""SELECT portfolio_token FROM student_profiles
                       WHERE user_id=%s""", (placement["student_id"],))
    if not token:
        execute("""UPDATE student_profiles
                      SET portfolio_public=TRUE, portfolio_token='tok-v26'
                    WHERE user_id=%s""", (placement["student_id"],))
        token = "tok-v26"
    else:
        execute("""UPDATE student_profiles SET portfolio_public=TRUE
                    WHERE user_id=%s""", (placement["student_id"],))

public = app.test_client().get(f"/p/{token}").data.decode()
step("a stranger does not see it while it is hidden",
     "Employer verified feedback" not in public)

student.post(f"/student/praxfolio/verdict/{A}", data={"show": "1"})
public = app.test_client().get(f"/p/{token}").data.decode()
step("the student can publish it", "Employer verified feedback" in public)
step("and the company is named as the source", "signed off the work" in public)

student.post(f"/student/praxfolio/verdict/{A}", data={"show": "0"})
public = app.test_client().get(f"/p/{token}").data.decode()
step("and can take it down again",
     "Employer verified feedback" not in public)

if other_student:
    r = login(other_student["email"]).post(
        f"/student/praxfolio/verdict/{A}", data={"show": "1"})
    step("another student cannot publish it", r.status_code == 404,
         r.status_code)
    with app.app_context():
        step("and it really is still hidden",
             ef.for_assignment(A)["is_public"] is False)

# A student must not be able to edit what was said about them. There is no
# route that would let them; this asserts that stays true.
step("there is no student route that writes feedback",
     not any("feedback" in str(r.rule) and "student" in str(r.rule)
             for r in app.url_map.iter_rules()
             if r.methods and "POST" in r.methods
             and "verdict" not in str(r.rule)))

# ------------------------------------------------------------- averaging
print("\n--- averages ---\n")

step("nothing rated gives no summary", ef.summarise({}) is None)

sample = {1: {"communication": 5, "problem_solving": 3, "quality": 4,
              "professionalism": 4, "overall": 4.0},
          2: {"communication": 3, "problem_solving": 3, "quality": 2,
              "professionalism": 4, "overall": 3.0}}
s = ef.summarise(sample)
step("two ratings average per competency", s["communication"] == 4.0
     and s["quality"] == 3.0, s)
step("and overall", s["overall"] == 3.5, s["overall"])
step("and the count is the number of projects", s["count"] == 2)

# ---------------------------------------------- arriving before migration
print("\n--- code ahead of its migration ---\n")

with app.app_context():
    execute("ALTER TABLE employer_feedback RENAME TO employer_feedback_hidden")
try:
    ef._warned = False
    with app.app_context():
        step("reading one placement degrades to nothing",
             ef.for_assignment(A) is None)
        step("reading a student's feedback degrades to nothing",
             ef.for_student(placement["student_id"]) == {})
        step("and the rated-set degrades to empty",
             ef.with_feedback([A]) == set())

    step("the student's Praxfolio still answers",
         login(placement["student_email"]).get(
             "/student/praxfolio").status_code == 200)
    step("the public Praxfolio still answers",
         app.test_client().get(f"/p/{token}").status_code == 200)
    step("and the company's progress page still answers",
         login(placement["company_email"]).get(
             f"/company/projects/{placement['project_id']}/progress"
         ).status_code == 200)
finally:
    with app.app_context():
        execute("ALTER TABLE employer_feedback_hidden RENAME TO employer_feedback")

print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
