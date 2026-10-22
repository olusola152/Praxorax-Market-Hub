"""Session helpers, route guards and subscription checks."""

import re
import secrets
import string
import time
from functools import wraps

from flask import (current_app, flash, g, jsonify, redirect, request, session,
                   url_for)

from db import execute, query

DASHBOARDS = {
    "student": "student.dashboard",
    "lecturer": "lecturer.dashboard",
    "university": "university.dashboard",
    "company": "company.dashboard",
    "admin": "admin.dashboard",
}

ROLE_LABELS = {
    "student": "Student",
    "lecturer": "Lecturer",
    "university": "University",
    "company": "Company",
    "admin": "Administrator",
}


def load_current_user():
    """Runs before every request; puts the signed-in user on g.user."""
    g.user = None
    user_id = session.get("user_id")
    if not user_id:
        return

    user = query(
        """SELECT u.id, u.fullname, u.email, u.role, u.status,
                  u.email_notifications,
                  c.id AS company_id, c.name AS company_name,
                  c.subscription_status AS company_subscription,
                  c.subscribed_until AS company_until,
                  lp.university_id AS lecturer_university_id,
                  sp.university_id AS student_university_id,
                  sp.field_id AS student_field_id
             FROM users u
             LEFT JOIN companies c ON c.user_id = u.id
             LEFT JOIN lecturer_profiles lp ON lp.user_id = u.id
             LEFT JOIN student_profiles sp ON sp.user_id = u.id
            WHERE u.id = %s""", (user_id,), one=True)

    # A blocked or deleted account loses its session on the next request.
    if user is None or user["status"] == "blocked":
        session.clear()
        return

    g.user = user

    if user["role"] == "university":
        g.university = query(
            """SELECT id, name, slug, subscription_status, subscribed_until
                 FROM universities WHERE admin_user_id = %s""", (user_id,), one=True)
    elif user["role"] == "lecturer":
        g.university = query(
            """SELECT id, name, slug, subscription_status, subscribed_until
                 FROM universities WHERE id = %s""",
            (user["lecturer_university_id"],), one=True)
    elif user["role"] == "student":
        g.university = query(
            """SELECT u.id, u.name, u.slug, u.subscription_status, u.subscribed_until
                 FROM universities u WHERE u.id = %s""",
            (user["student_university_id"],), one=True)
    else:
        g.university = None


def sign_in(user):
    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]
    session["seen"] = time.time()
    session.permanent = True
    execute("UPDATE users SET last_login_at = NOW() WHERE id = %s", (user["id"],))


# --------------------------------------------------------------- idle timeout
#
# A session ends after a period with no activity. Two things make this
# trustworthy rather than decorative:
#
#   * The clock lives in the session cookie, which is signed, so a browser
#     cannot wind it back. Nothing here trusts a value the page sent.
#   * The check runs before every request, so an expired session cannot be
#     used even by a tab that never reloaded.
#
# "Activity" means the person did something. A request is activity; so is a
# keystroke or a click, reported by the heartbeat in static/js/session.js,
# because somebody typing a long submission is not idle and should not lose
# it. Simply having the tab open is not activity.

# Requests that are not activity.
#
# Static files are not a person doing something — a page's own assets would
# otherwise refresh the clock on every load.
#
# The heartbeat is the subtle one. It has to be allowed through so it can
# report the time remaining, but it must not refresh the clock on its own,
# or the page's own "how long have I got?" question would answer itself and
# no session with JavaScript running would ever expire. It refreshes the
# clock only when it says it is reporting real activity, with ?keepalive=1.
IDLE_IGNORE = ("/static/", "/favicon")
IDLE_NO_TOUCH = ("/session/ping",)


def idle_limit():
    """Seconds of inactivity allowed, or 0 when the timeout is switched off."""
    return current_app.config.get("IDLE_TIMEOUT_MINUTES", 0) * 60


def seconds_left():
    """How long the current session has before it expires, or None."""
    limit = idle_limit()
    if not limit or not session.get("user_id"):
        return None
    return max(0, int(session.get("seen", 0) + limit - time.time()))


def touch_session():
    """Mark the session as active now."""
    if session.get("user_id"):
        session["seen"] = time.time()
        session.permanent = True


def enforce_idle_timeout():
    """Runs before every request. Returns a response when the session is over.

    On expiry the person is sent to the sign-in page with a message saying
    what happened and where they were, so they land back on the page they
    were using rather than on a bare dashboard.
    """
    limit = idle_limit()
    if not limit or not session.get("user_id"):
        return None
    if any(request.path.startswith(p) for p in IDLE_IGNORE):
        return None

    if time.time() - session.get("seen", 0) < limit:
        # Still live. Whether that counts as activity is a separate question:
        # the heartbeat decides for itself.
        if not any(request.path.startswith(p) for p in IDLE_NO_TOUCH):
            touch_session()
        return None

    session.clear()

    # An asynchronous caller gets an answer it can act on rather than a login
    # page it would have to parse.
    if (any(request.path.startswith(p) for p in IDLE_NO_TOUCH)
            or request.accept_mimetypes.best == "application/json"):
        return jsonify({"signed_in": False, "reason": "idle"}), 401

    nxt = request.full_path.rstrip("?") if request.method == "GET" else None
    return redirect(url_for("auth.login", timeout=1, next=nxt))


def dashboard_for(role):
    return url_for(DASHBOARDS.get(role, "auth.login"))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.get("user"):
            flash("Sign in to continue.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in roles:
                flash("That area belongs to a different account type.", "error")
                return redirect(dashboard_for(g.user["role"]))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def subscription_required(view):
    """Blocks paid actions when the account is not on an active subscription.

    Read-only pages stay open so an expired account can still see its data and
    renew; only the actions that consume the service are gated.
    """

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_app.config.get("DEMO_MODE"):
            return view(*args, **kwargs)

        from workflow import subscription_live

        role = g.user["role"]
        if role == "company" and not subscription_live(
                g.user["company_subscription"], g.user["company_until"]):
            flash("Your company subscription is not active. Renew it to carry on.",
                  "error")
            return redirect(url_for("company.dashboard"))

        # An independent student pays nothing and belongs to no institution,
        # so there is no subscription to check. They are gated elsewhere: a
        # company still has to accept their application.
        if is_independent_student():
            return view(*args, **kwargs)

        if role in ("university", "lecturer", "student"):
            uni = g.get("university")
            if not uni or not subscription_live(
                    uni["subscription_status"], uni["subscribed_until"]):
                flash(f"{uni['name'] if uni else 'Your institution'}'s subscription "
                      "has expired. Nothing can be done here until it is renewed.",
                      "error")
                return redirect(dashboard_for(role))
        return view(*args, **kwargs)

    return wrapped


def is_independent_student(user=None):
    """True when the signed-in student joined on the main page.

    Independent students have no university_id on their profile. They browse
    and apply for projects themselves, and the company supervises the work
    with no lecturer in the chain.
    """
    user = user or g.get("user")
    if not user or user["role"] != "student":
        return False
    return user.get("student_university_id") is None


def slugify(value, existing=None):
    """URL-safe name for a university's own join page."""
    base = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:70] or "university"
    slug = base
    n = 2
    while existing and slug in existing:
        slug = f"{base}-{n}"
        n += 1
    return slug


PASSCODE_ALPHABET = string.ascii_uppercase + string.digits
AMBIGUOUS = {"O", "0", "I", "1"}


def generate_passcode(groups=3, size=4):
    """A readable one-time code, e.g. XK4T-9PQR-2MBD.

    Ambiguous characters are excluded because these get read aloud and typed
    by hand from a printed list.
    """
    pool = [c for c in PASSCODE_ALPHABET if c not in AMBIGUOUS]
    return "-".join(
        "".join(secrets.choice(pool) for _ in range(size)) for _ in range(groups))


def log_action(action, target_type=None, target_id=None, detail=None):
    actor = g.user["id"] if g.get("user") else None
    execute(
        """INSERT INTO audit_log (actor_id, action, target_type, target_id, detail)
           VALUES (%s, %s, %s, %s, %s)""",
        (actor, action, target_type, target_id, detail))
