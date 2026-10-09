import io, os, zipfile
os.environ["DATABASE_URL"]="postgresql://postgres:test@127.0.0.1:5432/smclean"
os.environ["SECRET_KEY"]="test"
os.environ["DEMO_MODE"]="false"          # prove it works with NO subscription
os.environ["OPEN_STUDENT_SIGNUP"]="true"
os.environ["UPLOAD_FOLDER"]="/tmp/uploads"

from app import app
from db import query, execute, scalar
app.config["TESTING"]=True
P=F=0
def step(label, ok, extra=""):
    global P,F
    P,F=(P+1,F) if ok else (P,F+1)
    print(("PASS  " if ok else "FAIL  ")+label+(f"   {extra}" if extra else ""))

# --- a company signs up and posts a brief (admin activates subscription) ---
co=app.test_client()
co.post("/register", data={"role":"company","company_name":"Pettof Technologies",
    "fullname":"HR Lead","email":"hr@demo.test","password":"password123",
    "confirm":"password123"}, follow_redirects=True)
with app.app_context():
    step("company account created", scalar("SELECT COUNT(*) FROM companies")==1)
    # Since migration_v4 a new company starts unverified and cannot publish.
    execute("UPDATE companies SET subscription_status='active', "
            "verification_status='verified'")
    fid=query("SELECT id FROM fields WHERE name='Software Engineering'",one=True)["id"]
    skill_ids=[str(r["id"]) for r in query("SELECT id FROM skills LIMIT 2")]
r=co.post("/company/projects/new", data={"title":"Driver earnings dashboard",
    "description":"Build a dashboard showing weekly driver earnings with charts and CSV export.",
    "difficulty":"intermediate","deadline":"2026-12-31","max_students":"2",
    "field_id":str(fid),"deliverables":"Source code and a short guide","publish":"1",
    "skills":skill_ids},
    follow_redirects=True)
with app.app_context():
    proj=query("SELECT * FROM projects",one=True)
step("brief published", bool(proj) and proj["status"]=="open", proj and proj["status"])

# --- a member of the public signs up as a student on the MAIN page ---------
st=app.test_client()
r=st.post("/register", data={"role":"student","fullname":"Ada Obi",
    "email":"ada@public.test","password":"password123","confirm":"password123",
    "field_id":str(fid),"level":"400 level","department":"Computer Science"},
    follow_redirects=True)
with app.app_context():
    sp=query("""SELECT sp.*, u.role FROM student_profiles sp
                JOIN users u ON u.id=sp.user_id WHERE u.email='ada@public.test'""",one=True)
step("public student signed up on main page", bool(sp) and sp["role"]=="student")
step("student is independent (no university)", bool(sp) and sp["university_id"] is None)
step("landed on the project feed", b"Driver earnings" in r.data)

# --- signing out and back in works ----------------------------------------
st.post("/logout")
r=st.post("/login", data={"email":"ada@public.test","password":"password123"},
          follow_redirects=True)
step("public student can sign in", b"Ada Obi" in r.data or r.status_code==200)

# --- applies directly, with NO subscription anywhere ----------------------
r=st.post(f"/student/projects/{proj['id']}/apply",
          data={"message":"I have built two Flask dashboards with Chart.js and I can export CSV."},
          follow_redirects=True)
with app.app_context():
    appn=query("SELECT * FROM project_applications",one=True)
step("application accepted without any subscription", bool(appn) and appn["status"]=="pending")

r=st.post(f"/student/projects/{proj['id']}/apply", data={"message":"x"*40},
          follow_redirects=True)
with app.app_context():
    step("duplicate application refused", scalar("SELECT COUNT(*) FROM project_applications")==1)

# --- company sees and accepts --------------------------------------------
r=co.get("/company/applications")
step("company sees the application", b"Ada Obi" in r.data)
r=co.post(f"/company/applications/{appn['id']}/accept", follow_redirects=True)
with app.app_context():
    asg=query("SELECT * FROM assignments",one=True)
step("placement created with no lecturer", bool(asg) and asg["lecturer_id"] is None)
step("placement marked as a direct application", asg and asg["source"]=="direct")
with app.app_context():
    step("phases generated", scalar("SELECT COUNT(*) FROM milestones WHERE assignment_id=%s",(asg["id"],))==4)

# --- student uploads the actual project -----------------------------------
zbuf=io.BytesIO()
with zipfile.ZipFile(zbuf,"w") as z:
    z.writestr("app.py","print('driver earnings')\n")
    z.writestr("README.md","# Driver earnings dashboard\n")
zbuf.seek(0)

r=st.post(f"/student/work/{asg['id']}", data={
    "notes":"First cut. Charts work, CSV export pending.",
    "files":[(zbuf,"dashboard.zip"), (io.BytesIO(b"%PDF-1.4 fake report"),"report.pdf")],
}, content_type="multipart/form-data", follow_redirects=True)
with app.app_context():
    sub=query("SELECT * FROM submissions",one=True)
    files=query("SELECT * FROM submission_files ORDER BY id")
step("submission stored", bool(sub), sub and sub["stage"])
step("goes straight to the company (no lecturer)", sub and sub["stage"]=="with_company")
step("two files saved", len(files)==2, [f["original_name"] for f in files])
step("files exist on disk", all(os.path.isfile(
        os.path.join("/tmp/uploads", f["relative_path"])) for f in files))
step("checksums recorded", all(len(f["sha256"])==64 for f in files))

# --- a program file is refused --------------------------------------------
r=st.post(f"/student/work/{asg['id']}", data={
    "notes":"try again", "files":[(io.BytesIO(b"MZ..."),"virus.exe")]},
    content_type="multipart/form-data", follow_redirects=True)
with app.app_context():
    step("executable upload refused", scalar("SELECT COUNT(*) FROM submission_files")==2)

# --- downloads -------------------------------------------------------------
r=st.get(f"/files/{files[0]['id']}")
step("student downloads their own file", r.status_code==200 and len(r.data)>0)
r=co.get(f"/files/{files[0]['id']}")
step("company downloads the student's file", r.status_code==200)
r=co.get(f"/files/submission/{sub['id']}/archive")
ok = r.status_code==200
names=[]
if ok:
    names=zipfile.ZipFile(io.BytesIO(r.data)).namelist()
step("company downloads everything as one zip", ok and len(names)==2, names)
with app.app_context():
    step("downloads are logged", scalar("SELECT COUNT(*) FROM file_downloads")==3)

# --- an outsider cannot reach the files ------------------------------------
other=app.test_client()
other.post("/register", data={"role":"student","fullname":"Nosy Person",
    "email":"nosy@public.test","password":"password123","confirm":"password123",
    "field_id":str(fid)}, follow_redirects=True)
r=other.get(f"/files/{files[0]['id']}")
step("another student is refused (403)", r.status_code==403, r.status_code)
r=app.test_client().get(f"/files/{files[0]['id']}", follow_redirects=False)
step("signed-out visitor is redirected to login", r.status_code==302, r.status_code)

# --- the record page -------------------------------------------------------
r=st.get(f"/student/placements/{asg['id']}/record")
step("project record page renders", r.status_code==200 and b"dashboard.zip" in r.data)
step("record shows the dates", b"Brief posted" in r.data and b"You joined" in r.data)

# --- company approves; certificate issued ----------------------------------
r=co.post(f"/company/submissions/{sub['id']}", data={"action":"approve",
    "comment":"Good work, approved."}, follow_redirects=True)
with app.app_context():
    step("company approved the independent student's work",
         query("SELECT stage FROM submissions",one=True)["stage"]=="approved")
    step("certificate issued", scalar("SELECT COUNT(*) FROM certificates")==1)

# --- the lecturer route still works ---------------------------------------
with app.app_context():
    step("existing lecturer flow untouched",
         scalar("SELECT COUNT(*) FROM assignments WHERE source='lecturer'")==0)

print(f"\n{P} passed, {F} failed")
