"""Content must not end up underneath the photographic backdrop.

The backdrop is injected from the base template for anything carrying the
gate shell. The first version raised .gate-shell, .card and .panel above it
by name — which silently buried any page built from something else. Two
pages were: the certificate and the verification page, which are the two
surfaces somebody outside the platform actually opens, and the only ones
whose whole purpose is to be readable by a stranger.

So this is not only about those two pages. It is about the rule that
replaced the list: everything inside <main> sits above the backdrop,
whatever classes it happens to use, and some pages opt out of the backdrop
entirely because they are documents rather than screens.

Run after seed_demo.py.
"""
import json
import os
import re
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up23",
                  TRIAL_DAYS="0", BASE_URL="https://praxorax.test")

from app import app
from db import execute, query

app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = open(os.path.join(ROOT, "static", "css", "style.css")).read()
pub = app.test_client()

# ------------------------------------------------- the rule that replaced
print("\n--- everything in main is above the backdrop ---\n")

step("the wrapper is raised, not a list of inner classes",
     re.search(r"body\.gate:not\(\.landing-page\)\s+main\s*\{[^}]*z-index:\s*1",
               CSS) is not None)
step("and the backdrop sits below it",
     re.search(r"\.gate-art\s*\{[^}]*z-index:\s*0", CSS) is not None)

# ------------------------------------------- documents carry no photograph
print("\n--- documents are not screens ---\n")

with app.app_context():
    stu = query("SELECT id, fullname FROM users WHERE role='student' ORDER BY id LIMIT 1",
                one=True)
    execute("DELETE FROM portfolio_certificates WHERE reference='PX-V23TEST'")
    snap = {
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "student": {"name": stu["fullname"], "field": "Computer Science"},
        "summary": {"projects": 1, "companies": 1,
                    "fields": ["Computer Science"], "skills": ["Flask"]},
        "projects": [{"title": "Driver earnings dashboard",
                      "company": "Pettof Technologies",
                      "field": "Computer Science", "difficulty": "intermediate",
                      "started": "2026-08-17", "completed": "2026-09-14",
                      "supervisor": "Dr Ngozi Eze",
                      "university": "University of Lagos",
                      "worked_as": "solo", "versions": 2, "files": 3,
                      "certificate": "PX-AAAABBBBCC"}],
    }
    execute("""INSERT INTO portfolio_certificates
               (student_id, reference, project_count, snapshot)
               VALUES (%s,'PX-V23TEST',1,%s)""", (stu["id"], json.dumps(snap)))

r = pub.get("/certificate/PX-V23TEST")
page = r.data.decode()
step("a certificate opens to anyone", r.status_code == 200, r.status_code)
step("with no photograph behind it", 'class="gate-art"' not in page)
step("and it is on paper, not on the dark ground", "certificate-page" in page)

# The content has to actually be there, not merely returned.
step("it names the student", stu["fullname"] in page)
step("it lists the work", "Driver earnings dashboard" in page)
step("it names the company that commissioned it", "Pettof Technologies" in page)
step("and the supervising lecturer", "Dr Ngozi Eze" in page)
step("it shows the reference", "PX-V23TEST" in page)
step("and says where to check it", "/verify" in page)
step("it offers a way to print", "print()" in page.lower())

r = pub.get("/verify")
page = r.data.decode()
step("verification opens to anyone", r.status_code == 200, r.status_code)
step("with no photograph behind it either", 'class="gate-art"' not in page)
step("and a field to paste a reference into", 'name="reference"' in page
     or "Reference number" in page)

# ----------------------------------------- the pages that do carry one
print("\n--- the pages that keep the photograph ---\n")

for path in ("/login", "/register"):
    page = pub.get(path).data.decode()
    step(f"{path} still has its backdrop", 'class="gate-art"' in page)
    step(f"{path} still shows its form", "<form" in page)

# ------------------------------------- nothing is left behind the backdrop
print("\n--- no page returns a body it then hides ---\n")

with app.app_context():
    uni = query("""SELECT slug FROM universities
                    WHERE subscription_status IN ('active','trial')
                    ORDER BY id LIMIT 1""", one=True)

PATHS = ["/", "/login", "/register", "/join", "/verify",
         "/certificate/PX-V23TEST"]
if uni:
    PATHS += [f"/u/{uni['slug']}", f"/u/{uni['slug']}/login",
              f"/u/{uni['slug']}/student", f"/u/{uni['slug']}/lecturer"]

for path in PATHS:
    r = pub.get(path)
    body = r.data.decode()
    ok = r.status_code == 200
    step(f"{path} answers", ok, r.status_code)
    if not ok:
        continue
    # Every one of these pages wears the gate shell, so each must either
    # opt out of the backdrop or raise its own content over it. There is
    # exactly one <main>, and the rule covers it.
    has_art = 'class="gate-art"' in body
    opted_out = any(k in body for k in
                    ("landing-page", "certificate-page", "plain-page"))
    step(f"{path} either has a backdrop or opts out, not neither",
         has_art or opted_out, f"art={has_art} opted_out={opted_out}")
    step(f"{path} has content inside main", "<main" in body
         and len(body.split("<main", 1)[1]) > 400)

with app.app_context():
    execute("DELETE FROM portfolio_certificates WHERE reference='PX-V23TEST'")

print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
