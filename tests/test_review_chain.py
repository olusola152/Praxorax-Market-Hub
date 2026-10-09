import io, os, zipfile
os.environ.update(DATABASE_URL="postgresql://postgres:test@127.0.0.1:5432/smtest",
                  SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/uploads")
from app import app
from db import query, execute
app.config["TESTING"]=True
P=F=0
def step(l,ok,x=""):
    global P,F
    P,F=(P+1,F) if ok else (P,F+1)
    print(("PASS  " if ok else "FAIL  ")+l+(f"   {x}" if x else ""))

def login(e,p="demo1234"):
    c=app.test_client(); c.post("/login",data={"email":e,"password":p}); return c

with app.app_context():
    execute("UPDATE universities SET subscription_status='active'")
    execute("UPDATE companies SET subscription_status='active'")
    asg=query("""SELECT a.id, a.student_id, u.email FROM assignments a
                 JOIN users u ON u.id=a.student_id
                WHERE a.lecturer_id IS NOT NULL AND a.status NOT IN ('completed','cancelled')
                LIMIT 1""",one=True)
    execute("""DELETE FROM submissions WHERE assignment_id=%s""",(asg["id"],))

st=login(asg["email"])
r=st.post(f"/student/work/{asg['id']}", data={
    "notes":"Phase 2 build, with the ERD attached.",
    "files":[(io.BytesIO(b"diagram bytes"),"erd.png")]},
    content_type="multipart/form-data", follow_redirects=True)
with app.app_context():
    sub=query("SELECT * FROM submissions WHERE assignment_id=%s",(asg["id"],),one=True)
step("supervised student's submission goes to the lecturer",
     sub and sub["stage"]=="with_lecturer", sub and sub["stage"])

lc=login("bello@demo.marketplace")
r=lc.get(f"/lecturer/submissions/{sub['id']}")
step("lecturer review page renders", r.status_code==200, r.status_code)
step("lecturer sees the uploaded file", b"erd.png" in r.data)
step("lecturer gets a zip button", b"Download everything as a .zip" in r.data)

with app.app_context():
    fid=query("SELECT id FROM submission_files WHERE submission_id=%s",(sub["id"],),one=True)["id"]
step("lecturer downloads the file", lc.get(f"/files/{fid}").status_code==200)

# forward up the chain
lc.post(f"/lecturer/submissions/{sub['id']}", data={"action":"forward","comment":"Looks right."},
        follow_redirects=True)
un=login("registrar@demo.marketplace")
r=un.get(f"/university/submissions/{sub['id']}")
step("university review page renders with files", r.status_code==200 and b"erd.png" in r.data, r.status_code)
step("university downloads the file", un.get(f"/files/{fid}").status_code==200)

un.post(f"/university/submissions/{sub['id']}", data={"action":"forward","comment":"Passed on."},
        follow_redirects=True)
co=login("hr@demo.marketplace")
r=co.get(f"/company/submissions/{sub['id']}")
step("company review page renders with files", r.status_code==200 and b"erd.png" in r.data, r.status_code)
step("company downloads the zip", co.get(f"/files/submission/{sub['id']}/archive").status_code==200)

# somebody who is not on this placement must not reach it
others = [e for e in ("chidi@demo.marketplace","funke@demo.marketplace",
                      "emeka@demo.marketplace") if e != asg["email"]]
for email in others:
    step(f"unrelated student {email.split('@')[0]} refused",
         login(email).get(f"/files/{fid}").status_code==403,
         login(email).get(f"/files/{fid}").status_code)
step("the placement's own student still gets their file",
     login(asg["email"]).get(f"/files/{fid}").status_code==200)
step("a lecturer from another university is refused",
     login("okafor@demo.marketplace").get(f"/files/{fid}").status_code in (403,401,302))

print(f"\n{P} passed, {F} failed")
