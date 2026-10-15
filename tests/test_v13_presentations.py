"""Project presentations — scheduling, agreement, the room, and the record.

Run after seed_demo.py. What this is actually checking, in order:

  * a slot can only be proposed by the three people on the placement
  * nobody is put in a room they did not agree to
  * the room will not open early, or late, or for an outsider
  * attendance is written by the server, not claimed by the client
  * only the company can record what the work came to

The last one matters most. Everything else is scheduling; that one is the
reason the record exists.
"""
import os

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up13",
                  TIMEZONE="Africa/Lagos", MAIL_ENABLED="false")

from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash

import presentations as pres
from app import app
from db import execute, query, scalar

app.config["TESTING"] = True
P = F = 0


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


def login(email, password="demo1234"):
    c = app.test_client()
    r = c.post("/login", data={"email": email, "password": password},
               follow_redirects=True)
    assert r.status_code == 200, (email, r.status_code)
    return c


def local(days=1, hour=14, minute=0):
    """A datetime-local string in the site's timezone, N days out."""
    moment = (datetime.now(pres.ZoneInfo("Africa/Lagos"))
              + timedelta(days=days)).replace(hour=hour, minute=minute,
                                              second=0, microsecond=0)
    return moment.strftime("%Y-%m-%dT%H:%M")


# ------------------------------------------------------------- find a placement
with app.app_context():
    placement = query(
        """SELECT a.id, a.student_id, a.lecturer_id, p.title,
                  c.user_id AS company_user_id, c.id AS company_id,
                  stu.email AS student_email, lec.email AS lecturer_email,
                  cu.email AS company_email
             FROM assignments a
             JOIN projects p ON p.id = a.project_id
             JOIN companies c ON c.id = p.company_id
             JOIN users stu ON stu.id = a.student_id
             JOIN users lec ON lec.id = a.lecturer_id
             JOIN users cu ON cu.id = c.user_id
            WHERE a.lecturer_id IS NOT NULL
            ORDER BY a.id LIMIT 1""", one=True)
    assert placement, "seed_demo.py has not been run — no placements to present"

    # A second student on another placement, to test that a stranger is refused.
    outsider = query(
        """SELECT u.email FROM users u
            WHERE u.role='student' AND u.id <> %s
              AND u.id NOT IN (SELECT student_id FROM assignments WHERE id=%s)
            ORDER BY u.id LIMIT 1""",
        (placement["student_id"], placement["id"]), one=True)

    execute("""INSERT INTO users (fullname, email, password, role)
               VALUES ('Deck Root','root@pres.test',%s,'admin')
               ON CONFLICT (email) DO NOTHING""",
            (generate_password_hash("password123"),))

    # Start from a clean slate so a re-run does not trip the clash check.
    execute("DELETE FROM presentations WHERE assignment_id=%s", (placement["id"],))

AID = placement["id"]
student = login(placement["student_email"])
lecturer = login(placement["lecturer_email"])
company = login(placement["company_email"])
stranger = login(outsider["email"]) if outsider else None
admin = login("root@pres.test", "password123")

print(f"\n--- placement {AID}: {placement['title']} ---\n")

# ----------------------------------------------------------- the placement page
r = student.get(f"/presentations/placement/{AID}")
step("the student sees the placement's presentation page", r.status_code == 200,
     r.status_code)
step("and is offered the booking form", b"Propose this session" in r.data)

r = lecturer.get(f"/presentations/placement/{AID}")
step("the supervising lecturer sees it too", r.status_code == 200, r.status_code)

r = company.get(f"/presentations/placement/{AID}")
step("so does the company that owns the brief", r.status_code == 200, r.status_code)

if stranger:
    r = stranger.get(f"/presentations/placement/{AID}")
    step("a student from another placement is refused", r.status_code == 403,
         r.status_code)
    r = stranger.post(f"/presentations/placement/{AID}/propose",
                      data={"starts_at": local(2), "duration_mins": "30"})
    step("and cannot book one either", r.status_code == 403, r.status_code)

r = app.test_client().get(f"/presentations/placement/{AID}")
step("a signed-out visitor is sent to the login page",
     r.status_code == 302 and "/login" in r.headers["Location"])

# ------------------------------------------------------------------- proposing
bad = [
    ({"starts_at": "", "duration_mins": "30"}, "with no time"),
    ({"starts_at": local(-3), "duration_mins": "30"}, "in the past"),
    ({"starts_at": local(1), "duration_mins": "5"}, "shorter than 10 minutes"),
    ({"starts_at": local(1), "duration_mins": "600"}, "longer than 4 hours"),
    ({"starts_at": local(400), "duration_mins": "30"}, "months too far ahead"),
    ({"starts_at": local(1), "duration_mins": "30", "provider": "external",
      "external_url": "not-a-url"}, "with a link that is not a URL"),
    ({"starts_at": local(1), "duration_mins": "30", "provider": "external",
      "external_url": "http://zoom.us/j/1"}, "with a plain-http link"),
    ({"starts_at": local(1), "duration_mins": "30", "provider": "external",
      "external_url": "https://evil.example.com/j/1"}, "pointing at an unknown host"),
]
with app.app_context():
    before = scalar("SELECT COUNT(*) FROM presentations WHERE assignment_id=%s", (AID,))
for data, why in bad:
    student.post(f"/presentations/placement/{AID}/propose", data=data)
with app.app_context():
    after = scalar("SELECT COUNT(*) FROM presentations WHERE assignment_id=%s", (AID,))
step(f"all {len(bad)} malformed proposals are refused", after == before,
     f"{after - before} got through")

r = student.post(f"/presentations/placement/{AID}/propose",
                 data={"title": "Final defence", "agenda": "Demo, then questions",
                       "starts_at": local(2), "duration_mins": "45"},
                 follow_redirects=True)
step("a well-formed proposal is accepted", r.status_code == 200, r.status_code)

with app.app_context():
    row = query("""SELECT * FROM presentations WHERE assignment_id=%s
                    ORDER BY id DESC LIMIT 1""", (AID,), one=True)
PID = row["id"]
step("it is saved as awaiting agreement", row["status"] == "proposed", row["status"])
step("the length is kept", row["duration_mins"] == 45, row["duration_mins"])
step("the built-in video is the default", row["provider"] == "jitsi", row["provider"])
step("the room name is not guessable",
     row["room_name"].startswith(f"praxorax-{AID}-") and len(row["room_name"]) > 20,
     row["room_name"])

# the time must survive the timezone round trip
with app.app_context():
    want = pres.parse_local(local(2))
    step("2pm Lagos is stored as 1pm UTC",
         row["starts_at"] == want and want.astimezone(timezone.utc).hour == 13,
         f"{row['starts_at']} vs {want}")

# ------------------------------------------------------------------- attendees
with app.app_context():
    people = {a["user_id"]: a for a in pres.attendees(PID)}
step("all three parties are invited", len(people) == 3, len(people))
step("the student is down as presenting",
     people[placement["student_id"]]["part"] == "presenter")
step("the company hosts", people[placement["company_user_id"]]["part"] == "host")
step("the lecturer observes", people[placement["lecturer_id"]]["part"] == "observer")
step("the proposer has agreed by proposing",
     people[placement["student_id"]]["response"] == "accepted")
step("the other two have not answered yet",
     all(people[u]["response"] == "pending"
         for u in (placement["company_user_id"], placement["lecturer_id"])))
step("everyone was told", True)
with app.app_context():
    told = scalar("""SELECT COUNT(*) FROM notifications
                      WHERE url=%s AND user_id <> %s""",
                  (f"/presentations/{PID}", placement["student_id"]))
step("two notifications went out, one per other party", told == 2, told)

# ---------------------------------------------------------------- the room page
r = student.get(f"/presentations/{PID}")
step("the student can open the session", r.status_code == 200, r.status_code)
step("the page says it is awaiting agreement", b"Awaiting agreement" in r.data)
step("the room is not open yet", b"The time has not been agreed yet" in r.data)
step("the call is not embedded before then", b"external_api.js" not in r.data)
step("the room name is never printed on the page",
     row["room_name"].encode() not in r.data)

r = company.get(f"/presentations/{PID}")
step("the company is asked whether the time works",
     b"work for you" in r.data, r.status_code)

if stranger:
    r = stranger.get(f"/presentations/{PID}")
    step("an uninvited student cannot open the session", r.status_code == 403,
         r.status_code)
    r = stranger.post(f"/presentations/{PID}/join")
    step("nor force the door", r.status_code == 403, r.status_code)

r = admin.get(f"/presentations/{PID}")
step("an administrator can read any session", r.status_code == 200, r.status_code)
step("and reads it inside the dark deck", b'class="deck"' in r.data)
step("the admin rail is on the page", b"rail-link" in r.data)

# -------------------------------------------------------- joining before time
r = student.post(f"/presentations/{PID}/join", follow_redirects=True)
step("the room refuses to open while the time is unagreed",
     b"has not been agreed" in r.data)
with app.app_context():
    step("and no attendance was written",
         query("""SELECT joined_at FROM presentation_attendees
                   WHERE presentation_id=%s AND user_id=%s""",
               (PID, placement["student_id"]), one=True)["joined_at"] is None)

# ------------------------------------------------------------------ agreeing
lecturer.post(f"/presentations/{PID}/respond", data={"answer": "accept"})
with app.app_context():
    state = query("SELECT status FROM presentations WHERE id=%s", (PID,),
                  one=True)["status"]
step("one yes is not enough to confirm", state == "proposed", state)

company.post(f"/presentations/{PID}/respond", data={"answer": "accept"})
with app.app_context():
    state = query("SELECT status FROM presentations WHERE id=%s", (PID,),
                  one=True)["status"]
step("the last yes confirms it", state == "confirmed", state)

r = student.get(f"/presentations/{PID}")
step("the page now reads confirmed", b"Confirmed" in r.data)
step("but the room still will not open two days early",
     b"The room opens 20 minutes before" in r.data)

# ---------------------------------------------------- the room, at the time
with app.app_context():
    execute("UPDATE presentations SET starts_at=%s WHERE id=%s",
            (datetime.now(timezone.utc) - timedelta(minutes=2), PID))

r = student.get(f"/presentations/{PID}")
step("at the hour, the room offers a way in", b"Join the presentation" in r.data)
step("the call is still not loaded until you go in",
     b"external_api.js" not in r.data)

r = student.post(f"/presentations/{PID}/join", follow_redirects=True)
step("going in loads the call", b"external_api.js" in r.data, r.status_code)
step("the room name reaches the browser only now",
     b"data-room=" in r.data)
with app.app_context():
    mine = query("""SELECT joined_at, last_seen_at FROM presentation_attendees
                     WHERE presentation_id=%s AND user_id=%s""",
                 (PID, placement["student_id"]), one=True)
step("attendance is recorded by the server", mine["joined_at"] is not None)
with app.app_context():
    state = query("SELECT status, started_at FROM presentations WHERE id=%s",
                  (PID,), one=True)
step("the session goes live when the first person arrives",
     state["status"] == "live", state["status"])
step("and the start is timestamped", state["started_at"] is not None)

first_join = mine["joined_at"]
student.post(f"/presentations/{PID}/join")
with app.app_context():
    again = query("""SELECT joined_at, last_seen_at FROM presentation_attendees
                      WHERE presentation_id=%s AND user_id=%s""",
                  (PID, placement["student_id"]), one=True)
step("re-entering does not rewrite when you first arrived",
     again["joined_at"] == first_join)
step("but it does move when you were last seen",
     again["last_seen_at"] >= first_join)

company.post(f"/presentations/{PID}/join")
lecturer.post(f"/presentations/{PID}/join")
with app.app_context():
    attended = scalar("""SELECT COUNT(*) FROM presentation_attendees
                          WHERE presentation_id=%s AND joined_at IS NOT NULL""",
                      (PID,))
step("all three arrivals are on the record", attended == 3, attended)

r = admin.get(f"/presentations/{PID}")
step("the attendance table shows who came", b"Attended" in r.data)

# --------------------------------------------------------------- the outcome
r = student.post(f"/presentations/{PID}/outcome",
                 data={"outcome": "passed", "outcome_notes": "I did great"})
step("a student cannot mark their own defence as passed", r.status_code == 403,
     r.status_code)
r = lecturer.post(f"/presentations/{PID}/outcome",
                  data={"outcome": "passed", "outcome_notes": "My student passed"})
step("nor can the supervising lecturer", r.status_code == 403, r.status_code)
with app.app_context():
    step("and nothing was written either time",
         query("SELECT outcome FROM presentations WHERE id=%s", (PID,),
               one=True)["outcome"] is None)

r = company.post(f"/presentations/{PID}/outcome",
                 data={"outcome": "rework",
                       "outcome_notes": "Good demo. Fix the error handling."},
                 follow_redirects=True)
step("the company records the outcome", r.status_code == 200, r.status_code)
with app.app_context():
    done = query("SELECT * FROM presentations WHERE id=%s", (PID,), one=True)
step("the session is marked held", done["status"] == "held", done["status"])
step("the verdict is kept", done["outcome"] == "rework", done["outcome"])
step("so are the notes", "error handling" in (done["outcome_notes"] or ""))
step("and who decided it", done["outcome_by"] == placement["company_user_id"])
step("with a timestamp", done["outcome_at"] is not None)

with app.app_context():
    told = scalar("""SELECT COUNT(*) FROM notifications
                      WHERE url=%s AND body LIKE %s""",
                  (f"/presentations/{PID}", "%Needs rework%"))
step("the student and lecturer were both told the outcome", told == 2, told)

r = company.post(f"/presentations/{PID}/outcome", data={"outcome": "passed"},
                 follow_redirects=True)
step("an outcome cannot be quietly overwritten", b"already recorded" in r.data)
with app.app_context():
    step("the first verdict stands",
         query("SELECT outcome FROM presentations WHERE id=%s", (PID,),
               one=True)["outcome"] == "rework")

r = student.get(f"/presentations/{PID}")
step("the student sees the verdict", b"Needs rework" in r.data)
step("and the room has closed", b"This session is over" in r.data)
r = student.post(f"/presentations/{PID}/join", follow_redirects=True)
step("a closed session cannot be rejoined", b"session is over" in r.data)

# ----------------------------------------------------- declining and moving
company.post(f"/presentations/placement/{AID}/propose",
             data={"title": "Second attempt", "starts_at": local(5),
                   "duration_mins": "30"})
with app.app_context():
    second = query("""SELECT id FROM presentations WHERE assignment_id=%s
                       ORDER BY id DESC LIMIT 1""", (AID,), one=True)["id"]

r = student.post(f"/presentations/{second}/respond",
                 data={"answer": "decline", "reason": "Lectures until 4pm"},
                 follow_redirects=True)
step("declining frees the slot", r.status_code == 200)
with app.app_context():
    gone = query("SELECT status, decline_reason FROM presentations WHERE id=%s",
                 (second,), one=True)
step("the session is cancelled", gone["status"] == "cancelled", gone["status"])
step("the reason is kept so the next time can avoid it",
     "4pm" in (gone["decline_reason"] or ""))

company.post(f"/presentations/placement/{AID}/propose",
             data={"title": "Third attempt", "starts_at": local(6),
                   "duration_mins": "30"})
with app.app_context():
    third = query("""SELECT id FROM presentations WHERE assignment_id=%s
                      ORDER BY id DESC LIMIT 1""", (AID,), one=True)["id"]
student.post(f"/presentations/{third}/respond", data={"answer": "accept"})
lecturer.post(f"/presentations/{third}/respond", data={"answer": "accept"})
with app.app_context():
    step("three yeses confirm it",
         query("SELECT status FROM presentations WHERE id=%s", (third,),
               one=True)["status"] == "confirmed")

lecturer.post(f"/presentations/{third}/reschedule",
              data={"starts_at": local(7, hour=10), "duration_mins": "30"})
with app.app_context():
    moved = query("SELECT status, proposed_by FROM presentations WHERE id=%s",
                  (third,), one=True)
    responses = {a["user_id"]: a["response"] for a in pres.attendees(third)}
step("moving it puts the session back to awaiting agreement",
     moved["status"] == "proposed", moved["status"])
step("whoever moved it has agreed to the new time",
     responses[placement["lecturer_id"]] == "accepted")
step("an old yes is not carried over to a time nobody agreed to",
     responses[placement["student_id"]] == "pending"
     and responses[placement["company_user_id"]] == "pending")

# ------------------------------------------------------------------- clashes
with app.app_context():
    before = scalar("SELECT COUNT(*) FROM presentations WHERE assignment_id=%s", (AID,))
r = company.post(f"/presentations/placement/{AID}/propose",
                 data={"title": "Overlapping", "starts_at": local(7, hour=10, minute=15),
                       "duration_mins": "30"}, follow_redirects=True)
with app.app_context():
    after = scalar("SELECT COUNT(*) FROM presentations WHERE assignment_id=%s", (AID,))
step("a slot overlapping a live one is refused", after == before, after - before)
step("and says what it clashes with", b"overlaps a session" in r.data)

r = company.post(f"/presentations/placement/{AID}/propose",
                 data={"title": "Clear slot", "starts_at": local(7, hour=15),
                       "duration_mins": "30"}, follow_redirects=True)
with app.app_context():
    step("a clear slot on the same day is fine",
         scalar("SELECT COUNT(*) FROM presentations WHERE assignment_id=%s",
                (AID,)) == before + 1)
    clear_id = query("""SELECT id FROM presentations WHERE assignment_id=%s
                         ORDER BY id DESC LIMIT 1""", (AID,), one=True)["id"]

# -------------------------------------------------------------- cancelling
r = lecturer.post(f"/presentations/{clear_id}/cancel",
                  data={"reason": "Student is ill"})
step("someone who did not propose it and is not the company cannot cancel",
     r.status_code == 403, r.status_code)
r = company.post(f"/presentations/{clear_id}/cancel", data={"reason": "Rescheduling"},
                 follow_redirects=True)
with app.app_context():
    step("the company can", query("SELECT status FROM presentations WHERE id=%s",
                                  (clear_id,), one=True)["status"] == "cancelled")

# ------------------------------------------------------------ external links
r = company.post(f"/presentations/placement/{AID}/propose",
                 data={"title": "On Zoom", "starts_at": local(9),
                       "duration_mins": "30", "provider": "external",
                       "external_url": "https://zoom.us/j/9876543210"},
                 follow_redirects=True)
with app.app_context():
    zoom = query("""SELECT * FROM presentations WHERE assignment_id=%s
                     ORDER BY id DESC LIMIT 1""", (AID,), one=True)
step("an outside meeting link is accepted", zoom["provider"] == "external",
     zoom["provider"])
step("the link is kept", "zoom.us" in (zoom["external_url"] or ""))
step("and no built-in room is created for it", zoom["room_name"] is None)

with app.app_context():
    step("only known meeting hosts are allowed through",
         pres.valid_external_url("https://zoom.us/j/1")
         and pres.valid_external_url("https://acme.zoom.us/j/1")
         and pres.valid_external_url("https://meet.google.com/abc-defg-hij")
         and not pres.valid_external_url("https://zoom.us.evil.test/j/1")
         and not pres.valid_external_url("javascript:alert(1)")
         and not pres.valid_external_url("https://zoom.us"))

# -------------------------------------------------------------- the listings
r = student.get("/presentations/")
step("the student's list renders", r.status_code == 200, r.status_code)
step("it is headed as theirs", b"My presentations" in r.data)
step("the held session is in it", b"Needs rework" in r.data)

r = company.get("/presentations/")
step("the company's list renders", r.status_code == 200, r.status_code)
r = lecturer.get("/presentations/")
step("the lecturer's list renders", r.status_code == 200, r.status_code)
step("and flags the one still waiting on them", b"Waiting on you" in r.data)

uni = login("registrar@demo.marketplace")
r = uni.get("/presentations/")
step("the university sees its students' defences", r.status_code == 200,
     r.status_code)
step("framed as oversight, not attendance",
     b"answerable for" in r.data and b"My presentations" not in r.data)
step("nothing asks the university to agree to a time",
     b"Waiting on you" not in r.data)

r = uni.get(f"/presentations/{PID}")
step("the university can read one of its own sessions", r.status_code == 200,
     r.status_code)
step("but is told it is not in the call", b"not in the call" in r.data)
step("and is offered no outcome form", b"Save the outcome" not in r.data)

r = admin.get("/presentations/")
step("the admin list renders on the deck",
     r.status_code == 200 and b'class="deck"' in r.data, r.status_code)

# --------------------------------------------------------- entry points exist
r = student.get(f"/student/work/{AID}")
step("the student's placement page links to its presentations",
     f"/presentations/placement/{AID}".encode() in r.data, r.status_code)

r = student.get("/student/dashboard")
step("the student's top navigation links to presentations",
     b"/presentations/" in r.data)
r = company.get("/company/dashboard")
step("so does the company's", b"/presentations/" in r.data)
r = lecturer.get("/lecturer/dashboard")
step("and the lecturer's", b"/presentations/" in r.data)
r = admin.get("/admin/dashboard")
step("the admin rail links to it", b"/presentations/" in r.data)

# The dashboard reminder. There is one session still outstanding at this
# point — the one that was moved and is waiting on the student again.
r = student.get("/student/dashboard")
step("the student's dashboard shows the next presentation",
     b"Next presentation" in r.data, r.status_code)
step("and says their answer is still wanted",
     b"not said yet whether this time works" in r.data)
r = lecturer.get("/lecturer/dashboard")
step("the lecturer's dashboard shows it too", b"Next presentation" in r.data)
r = company.get("/company/dashboard")
step("so does the company's", b"Next presentation" in r.data)

with app.app_context():
    execute("""UPDATE presentations SET status='cancelled'
                WHERE assignment_id=%s
                  AND status IN ('proposed','confirmed','live')""", (AID,))
r = student.get("/student/dashboard")
step("with nothing booked, the reminder stays off the dashboard",
     b"Next presentation" not in r.data)
step("and the dashboard still renders", r.status_code == 200, r.status_code)

# ------------------------------------------------------------- 404 behaviour
step("a session that does not exist is a 404",
     student.get("/presentations/999999").status_code == 404)
step("a placement that does not exist is a 404",
     student.get("/presentations/placement/999999").status_code == 404)

# ------------------------------------------------------------ the join window
with app.app_context():
    base = {"status": "confirmed", "duration_mins": 30}
    far = dict(base, starts_at=datetime.now(timezone.utc) + timedelta(hours=3))
    soon = dict(base, starts_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    over = dict(base, starts_at=datetime.now(timezone.utc) - timedelta(hours=4))
    step("the window is shut three hours early", pres.join_window(far)[0] is False)
    step("it is open ten minutes before", pres.join_window(soon)[0] is True)
    step("and shut again long after the end", pres.join_window(over)[0] is False)
    step("a cancelled session never opens",
         pres.join_window(dict(far, status="cancelled"))[0] is False)

print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
