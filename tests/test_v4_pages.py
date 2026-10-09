import os
os.environ.update(DATABASE_URL="postgresql://postgres:test@127.0.0.1:5432/smtest",
                  SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/uploads")
from app import app
from db import query
app.config["TESTING"]=True
P=F=0
def step(l,ok,x=""):
    global P,F
    P,F=(P+1,F) if ok else (P,F+1)
    print(("PASS  " if ok else "FAIL  ")+l+(f"   {x}" if x else ""))
def login(e,p="demo1234"):
    c=app.test_client(); c.post("/login",data={"email":e,"password":p}); return c

for email,label,pages in [
  ("ada@demo.marketplace","student",["/teams/","/student/bookmarks","/student/profile","/student/projects?sort=match"]),
  ("hr@demo.marketplace","company",["/company/verification","/company/applications"]),
  ("bello@demo.marketplace","lecturer",["/lecturer/dashboard"]),
]:
    c=login(email)
    for page in pages:
        r=c.get(page); step(f"{label} {page}", r.status_code==200, r.status_code)

# deliverables page for the lecturer supervising a real placement
lc=login("bello@demo.marketplace")
with app.app_context():
    a=query("SELECT project_id FROM assignments WHERE lecturer_id=(SELECT id FROM users WHERE email='bello@demo.marketplace') LIMIT 1",one=True)
if a:
    r=lc.get(f"/deliverables/project/{a['project_id']}")
    step("lecturer can manage deliverables on their project", r.status_code==200, r.status_code)
    st=login("ada@demo.marketplace")
    step("student cannot", st.get(f"/deliverables/project/{a['project_id']}").status_code==403)

co=login("hr@demo.marketplace")
with app.app_context():
    p=query("SELECT id FROM projects WHERE company_id=(SELECT id FROM companies WHERE user_id=(SELECT id FROM users WHERE email='hr@demo.marketplace')) LIMIT 1",one=True)
step("company can manage deliverables on its own brief",
     co.get(f"/deliverables/project/{p['id']}").status_code==200)

st=login("ada@demo.marketplace")
step("seeded students have skills, so matches render",
     b"against your skills" in st.get("/student/projects").data)
print(f"\n{P} passed, {F} failed")
