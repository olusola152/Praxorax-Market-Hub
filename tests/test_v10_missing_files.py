"""What happens when a file record outlives its file. Run after seed_demo.py."""
import io, os
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up10")

from app import app
from db import query, execute
import storage
app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


def login(email, pw="demo1234"):
    c = app.test_client()
    c.post("/login", data={"email": email, "password": pw})
    return c


with app.app_context():
    execute("UPDATE universities SET subscription_status='active'")
    execute("UPDATE companies SET subscription_status='active', "
            "verification_status='verified'")
    asg = query("""SELECT a.id, u.email AS student_email, lu.email AS lecturer_email
                     FROM assignments a
                     JOIN users u ON u.id = a.student_id
                     JOIN users lu ON lu.id = a.lecturer_id
                    WHERE a.lecturer_id IS NOT NULL
                      AND a.status NOT IN ('completed','cancelled') LIMIT 1""", one=True)
    execute("DELETE FROM submissions WHERE assignment_id=%s", (asg["id"],))

st = login(asg["student_email"])
st.post(f"/student/work/{asg['id']}", data={
    "notes": "Three files.",
    "files": [(io.BytesIO(b"one"), "one.pdf"),
              (io.BytesIO(b"two"), "two.pdf"),
              (io.BytesIO(b"three"), "three.pdf")]},
    content_type="multipart/form-data", follow_redirects=True)

with app.app_context():
    sub = query("SELECT * FROM submissions WHERE assignment_id=%s", (asg["id"],), one=True)
    files = query("SELECT * FROM submission_files WHERE submission_id=%s ORDER BY id",
                  (sub["id"],))
step("three files stored", len(files) == 3, len(files))

lc = login(asg["lecturer_email"])
step("all three download", all(
    lc.get(f"/files/{f['id']}").status_code == 200 for f in files))

import zipfile
r = lc.get(f"/files/submission/{sub['id']}/archive")
step("archive holds all three",
     len(zipfile.ZipFile(io.BytesIO(r.data)).namelist()) == 3)

# now delete one file from disk, exactly as replacing the project folder does
with app.app_context():
    os.remove(storage.absolute_path(files[1]["relative_path"]))

r = lc.get(f"/files/{files[1]['id']}")
step("the missing one returns 410", r.status_code == 410, r.status_code)
step("the page explains what happened", b"no longer on the server" in r.data)
step("it says how to prevent it", b"UPLOAD_FOLDER" in r.data)
step("it is not a bare Gone page", b"uploaded again" in r.data or b"upload it again" in r.data)

step("the surviving files still download",
     lc.get(f"/files/{files[0]['id']}").status_code == 200
     and lc.get(f"/files/{files[2]['id']}").status_code == 200)

r = lc.get(f"/files/submission/{sub['id']}/archive")
step("archive still works, skipping the missing one", r.status_code == 200)
names = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
step("archive holds the two that survive", len(names) == 2, names)

# every file gone -> 410 on the archive too
with app.app_context():
    for f in (files[0], files[2]):
        os.remove(storage.absolute_path(f["relative_path"]))
r = lc.get(f"/files/submission/{sub['id']}/archive")
step("an empty archive returns 410 rather than an empty zip",
     r.status_code == 410, r.status_code)

# the company side behaves the same
lc.post(f"/lecturer/submissions/{sub['id']}", data={"action": "forward",
        "comment": "Passing it on."}, follow_redirects=True)
with app.app_context():
    reg = query("""SELECT uu.email FROM assignments a
                     JOIN lecturer_profiles lp ON lp.user_id = a.lecturer_id
                     JOIN universities un ON un.id = lp.university_id
                     JOIN users uu ON uu.id = un.admin_user_id
                    WHERE a.id=%s""", (asg["id"],), one=True)
un = login(reg["email"])
un.post(f"/university/submissions/{sub['id']}", data={"action": "forward",
        "comment": "On to you."}, follow_redirects=True)
with app.app_context():
    comp = query("""SELECT cu.email FROM assignments a
                      JOIN projects p ON p.id = a.project_id
                      JOIN companies c ON c.id = p.company_id
                      JOIN users cu ON cu.id = c.user_id
                     WHERE a.id=%s""", (asg["id"],), one=True)
co = login(comp["email"])
r = co.get(f"/company/submissions/{sub['id']}")
step("company review page still renders with files missing", r.status_code == 200)
r = co.get(f"/files/{files[0]['id']}")
step("company gets the explanation too", r.status_code == 410
     and b"no longer on the server" in r.data)

print(f"\n{P} passed, {F} failed")
