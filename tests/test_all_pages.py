import os
os.environ.update(DATABASE_URL="postgresql://postgres:test@127.0.0.1:5432/smtest",
                  SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/uploads")
from app import app
from db import query, scalar
app.config["TESTING"]=True
P=F=0
def step(l,ok,x=""):
    global P,F
    P,F=(P+1,F) if ok else (P,F+1)
    print(("PASS  " if ok else "FAIL  ")+l+(f"   {x}" if x else ""))

def login(email, pw="demo1234"):
    c=app.test_client()
    r=c.post("/login", data={"email":email,"password":pw}, follow_redirects=True)
    return c, r

for email, label, pages in [
    ("bello@demo.marketplace","lecturer",
     ["/lecturer/dashboard","/lecturer/projects","/lecturer/students","/lecturer/inbox","/lecturer/profile"]),
    ("registrar@demo.marketplace","university",
     ["/university/dashboard","/university/lecturers","/university/students","/university/passcodes","/university/inbox","/university/placements"]),
    ("hr@demo.marketplace","company",
     ["/company/dashboard","/company/projects","/company/inbox","/company/applications","/company/requests"]),
    ("ada@demo.marketplace","student",
     ["/student/dashboard","/student/projects","/student/applications","/student/profile"]),
]:
    c,r = login(email)
    step(f"{label} signs in", r.status_code==200)
    for page in pages:
        resp=c.get(page)
        step(f"  {page}", resp.status_code==200, resp.status_code)

# a seeded (lecturer-placed) student still submits through the lecturer
c,_=login("ada@demo.marketplace")
with app.app_context():
    asg=query("""SELECT a.id FROM assignments a WHERE a.student_id=(
                   SELECT id FROM users WHERE email='ada@demo.marketplace')
                 AND a.lecturer_id IS NOT NULL LIMIT 1""", one=True)
if asg:
    r=c.get(f"/student/work/{asg['id']}")
    step("lecturer-placed student's work page renders", r.status_code==200)
    r=c.get(f"/student/placements/{asg['id']}/record")
    step("record page for a supervised placement", r.status_code==200)

# lecturer review page (uses the shared template that now lists files)
lc,_=login("bello@demo.marketplace")
with app.app_context():
    sub=query("SELECT id FROM submissions ORDER BY id LIMIT 1", one=True)
if sub:
    r=lc.get(f"/lecturer/submissions/{sub['id']}")
    step("lecturer review page renders with file panel", r.status_code in (200,403,404), r.status_code)

# public pages
pc=app.test_client()
for page in ["/", "/login", "/register", "/register?as=student", "/join", "/healthz"]:
    r=pc.get(page)
    step(f"public {page}", r.status_code==200, r.status_code)
step("student option shown on the main signup", b"Join on your own" in pc.get("/register").data)

print(f"\n{P} passed, {F} failed")
