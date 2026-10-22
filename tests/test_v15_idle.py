"""Idle sign-out. Run after seed_demo.py.

The clock is wound by hand rather than waited out, so the whole suite runs in
a second. Everything here is server side, which is the half that has to be
right: the browser can only ask to stay signed in, never decide it.
"""
import os
import time

os.environ.setdefault("DATABASE_URL",
                      "postgresql://postgres:test@127.0.0.1:5432/smtest")
os.environ.update(SECRET_KEY="test", DEMO_MODE="false", UPLOAD_FOLDER="/tmp/up15",
                  TRIAL_DAYS="0", IDLE_TIMEOUT_MINUTES="20")

from app import app

app.config["TESTING"] = True
P = F = 0

WHO = {"email": "bello@demo.marketplace", "password": "demo1234"}
HOME = "/lecturer/dashboard"


def step(label, ok, extra=""):
    global P, F
    P, F = (P + 1, F) if ok else (P, F + 1)
    print(("PASS  " if ok else "FAIL  ") + label + (f"   {extra}" if extra else ""))


def fresh():
    c = app.test_client()
    c.post("/login", data=WHO)
    return c


def idle_for(client, minutes):
    """Wind this session's clock back, as real time would."""
    with client.session_transaction() as sess:
        sess["seen"] = time.time() - minutes * 60


def seen_age(client):
    with client.session_transaction() as sess:
        return time.time() - sess.get("seen", 0) if sess.get("seen") else None


# --------------------------------------------------------------- the basics
c = fresh()
step("signing in stamps the clock", seen_age(c) is not None and seen_age(c) < 5)
step("and the session works", c.get(HOME).status_code == 200)

idle_for(c, 19)
step("19 minutes idle is still signed in", c.get(HOME).status_code == 200)
step("and that request reset the clock", seen_age(c) < 5, seen_age(c))

idle_for(c, 21)
r = c.get(HOME)
step("21 minutes idle is signed out", r.status_code == 302, r.status_code)
step("sent to the sign-in page", "/login" in r.headers.get("Location", ""))
step("told it was a timeout", "timeout=1" in r.headers.get("Location", ""))
step("and where they were", "next=" + HOME in r.headers.get("Location", ""),
     r.headers.get("Location"))
step("the session really is gone", seen_age(c) is None)

# -------------------------------------------------------------- the message
c2 = fresh()
idle_for(c2, 25)
r = c2.get(HOME, follow_redirects=True)
step("the sign-in page says what happened", b"without activity" in r.data)
step("and names the period", b"20 minutes" in r.data)

# A one-minute timeout must not read "1 minutes".
app.config["IDLE_TIMEOUT_MINUTES"] = 1
c3 = fresh()
idle_for(c3, 2)
r = c3.get(HOME, follow_redirects=True)
step("one minute is spelled properly",
     b"after a minute" in r.data and b"1 minutes" not in r.data)
app.config["IDLE_TIMEOUT_MINUTES"] = 20

# ------------------------------------------------------- back where you were
c4 = fresh()
c4.get("/lecturer/students")
idle_for(c4, 21)
where = c4.get("/lecturer/students").headers["Location"]
r = c4.post(where, data=WHO)
step("signing back in returns you to the page you were on",
     r.headers.get("Location") == "/lecturer/students", r.headers.get("Location"))

# The return path is attacker-supplied, so it must stay on this site.
c5 = app.test_client()
r = c5.post("/login?next=https://evil.example.com", data=WHO)
step("an off-site return path is refused",
     r.headers.get("Location") == HOME, r.headers.get("Location"))
c6 = app.test_client()
r = c6.post("/login?next=//evil.example.com", data=WHO)
step("and so is a protocol-relative one",
     r.headers.get("Location") == HOME, r.headers.get("Location"))

# ------------------------------------------------------------- the heartbeat
c7 = fresh()
idle_for(c7, 15)
body = c7.post("/session/ping").get_json()
step("the heartbeat reports what is left", body["signed_in"] is True)
step("and counts down honestly", 250 < body["seconds_left"] < 320,
     body["seconds_left"])
step("asking the time does not reset the clock", seen_age(c7) > 600, seen_age(c7))

body = c7.post("/session/ping?keepalive=1").get_json()
step("reporting activity does reset it", seen_age(c7) < 5, seen_age(c7))
step("and the count goes back up", body["seconds_left"] > 1100,
     body["seconds_left"])

idle_for(c7, 21)
r = c7.post("/session/ping")
step("a heartbeat past the limit is refused", r.status_code == 401, r.status_code)
step("with an answer a script can act on",
     r.get_json()["signed_in"] is False and r.get_json()["reason"] == "idle")
c8 = fresh()
idle_for(c8, 21)
step("keepalive cannot revive a session that has already expired",
     c8.post("/session/ping?keepalive=1").status_code == 401)

# A signed-out visitor pinging gets a clean refusal, not a crash.
step("a signed-out heartbeat is refused",
     app.test_client().post("/session/ping").status_code == 401)

# ------------------------------------------------------- what is not activity
c9 = fresh()
idle_for(c9, 15)
c9.get("/static/css/style.css")
step("loading a stylesheet is not activity", seen_age(c9) > 600, seen_age(c9))

# ------------------------------------------------------------ switched off
app.config["IDLE_TIMEOUT_MINUTES"] = 0
c10 = fresh()
idle_for(c10, 60 * 8)
step("with the timeout off, eight hours idle stays signed in",
     c10.get(HOME).status_code == 200)
r = c10.get(HOME)
step("and no countdown is sent to the page", b"data-idle-limit" not in r.data)
app.config["IDLE_TIMEOUT_MINUTES"] = 20

# ------------------------------------------------------------- what the page gets
c11 = fresh()
r = c11.get(HOME)
step("a signed-in page carries the countdown", b"data-idle-limit=" in r.data)
step("and the limit in seconds", b'data-idle-limit="1200"' in r.data)
step("and where to send the heartbeat", b"/session/ping" in r.data)
step("and loads the script", b"js/session.js" in r.data)

anon = app.test_client().get("/")
step("a signed-out page carries none of it",
     b"data-idle-limit" not in anon.data and b"js/session.js" not in anon.data)

# ------------------------------------------------------------ signing out
c12 = fresh()
r = c12.post("/logout", follow_redirects=True)
step("signing out by hand still works", b"Signed out." in r.data)
step("and leaves nothing behind", seen_age(c12) is None)

print(f"\n{P} passed, {F} failed")
raise SystemExit(1 if F else 0)
