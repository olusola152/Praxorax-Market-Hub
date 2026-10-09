import re

from datetime import date, datetime, timedelta, timezone

from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import mailer
from auth_utils import dashboard_for, log_action, sign_in, slugify
from db import get_db, query
from security import clear_failures, login_blocked, record_failure

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")

# Companies and universities subscribe here. Students may also join here
# directly — with no institution behind them — when OPEN_STUDENT_SIGNUP is on.
# Lecturers still join through their own university's portal, because a
# lecturer needs a passcode from that institution.
ORG_ROLES = ("company", "university")


def signup_roles():
    if current_app.config.get("OPEN_STUDENT_SIGNUP", True):
        return ORG_ROLES + ("student",)
    return ORG_ROLES


def _base_checks(form, password, confirm):
    errors = []
    if len(form.get("fullname", "")) < 3:
        errors.append("Enter your full name.")
    if not EMAIL_RE.match(form.get("email", "")):
        errors.append("Enter a valid email address.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password != confirm:
        errors.append("The two passwords do not match.")
    return errors


def _website_ok(value):
    return not value or value.startswith(("http://", "https://"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Main-page signup — company, university, or an independent student."""
    if g.get("user"):
        return redirect(dashboard_for(g.user["role"]))

    roles = signup_roles()
    fields = query("SELECT id, name FROM fields ORDER BY name")
    form = {"role": request.args.get("as", "company")}
    if form["role"] not in roles:
        form["role"] = "company"

    if request.method == "POST":
        form = {k: v.strip() for k, v in request.form.items()}
        role = form.get("role", "")
        email = form.get("email", "").lower()
        form["email"] = email
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        errors = _base_checks(form, password, confirm)
        if role not in roles:
            errors.append("Choose an account type.")

        website = form.get("website", "")
        if not _website_ok(website):
            errors.append("The website must start with https://")

        if role == "company" and not form.get("company_name"):
            errors.append("Enter the company name.")
        if role == "university" and not form.get("university_name"):
            errors.append("Enter the institution name.")

        field_id = None
        if role == "student":
            raw_field = form.get("field_id", "")
            if raw_field.isdigit() and any(f["id"] == int(raw_field) for f in fields):
                field_id = int(raw_field)
            else:
                errors.append("Choose the area you study or work in.")

        if not errors and query("SELECT id FROM users WHERE email = %s", (email,), one=True):
            errors.append("That email is already registered. Sign in instead.")

        if role == "university" and form.get("university_name"):
            clash = query("SELECT id FROM universities WHERE lower(name) = lower(%s)",
                          (form["university_name"],), one=True)
            if clash:
                errors.append("That institution is already registered.")

        if errors:
            for m in errors:
                flash(m, "error")
            return render_template("auth/register.html", form=form,
                                   fields=fields, roles=roles), 400

        # Every organisation starts on a free week. No payment, no admin step —
        # they can post briefs or onboard lecturers the minute they sign up.
        trial_days = current_app.config.get("TRIAL_DAYS", 0)
        if trial_days > 0 and role in ("company", "university"):
            trial_status = "trial"
            trial_until = date.today() + timedelta(days=trial_days)
            trial_start = datetime.now(timezone.utc)
        else:
            trial_status, trial_until, trial_start = "pending", None, None

        conn = get_db()
        new_slug = None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO users (fullname, email, password, role)
                       VALUES (%s, %s, %s, %s) RETURNING id""",
                    (form["fullname"], email, generate_password_hash(password), role))
                user_id = cur.fetchone()["id"]

                if role == "student":
                    # university_id stays NULL. That is what marks this account
                    # as independent everywhere else in the app.
                    cur.execute(
                        """INSERT INTO student_profiles
                           (user_id, university_id, field_id, department, level, phone)
                           VALUES (%s, NULL, %s, %s, %s, %s)""",
                        (user_id, field_id,
                         form.get("department") or None,
                         form.get("level") or None,
                         form.get("phone") or None))
                elif role == "company":
                    cur.execute(
                        """INSERT INTO companies
                           (user_id, name, website, phone,
                            subscription_status, subscribed_until, trial_started_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (user_id, form["company_name"], website or None,
                         form.get("phone"), trial_status, trial_until, trial_start))
                else:
                    cur.execute("SELECT slug FROM universities")
                    taken = {r["slug"] for r in cur.fetchall()}
                    new_slug = slugify(form["university_name"], taken)
                    cur.execute(
                        """INSERT INTO universities
                           (name, slug, website, city, contact_email, admin_user_id,
                            subscription_status, subscribed_until, trial_started_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (form["university_name"], new_slug, website or None,
                         form.get("city"), email, user_id,
                         trial_status, trial_until, trial_start))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        sign_in({"id": user_id, "role": role})
        log_action("register", "user", user_id, role)
        mailer.send_welcome(current_app._get_current_object(), email,
                            form["fullname"], role)

        if role == "student":
            flash("Welcome. Browse the open briefs and apply for anything that "
                  "fits — no subscription needed.", "success")
            return redirect(url_for("student.browse"))

        if trial_status == "trial":
            flash(f"Your {trial_days}-day free trial has started — everything is "
                  f"open until {trial_until.strftime('%d %b %Y')}. No card needed.",
                  "success")
        else:
            flash("Account created. An administrator activates your subscription "
                  "once payment clears.", "success")

        if role == "university":
            # Show the institution its own portal first — that link is the
            # thing it will be sharing with staff and students.
            return redirect(url_for("portal.home", slug=new_slug))
        return redirect(dashboard_for(role))

    return render_template("auth/register.html", form=form, fields=fields,
                           roles=roles)


# ------------------------------------------------------------------ joining

@auth_bp.route("/join")
def join_index():
    """Directory of institution portals, for anyone who lost their link."""
    if current_app.config.get("DEMO_MODE"):
        unis = query(
            """SELECT id, name, slug, city, website, subscription_status
                 FROM universities ORDER BY name""")
    else:
        unis = query(
            """SELECT id, name, slug, city, website, subscription_status
                 FROM universities
                WHERE subscription_status = 'active' ORDER BY name""")
    return render_template("auth/join_index.html", universities=unis)


# ------------------------------------------------------------------ session

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user"):
        return redirect(dashboard_for(g.user["role"]))

    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if login_blocked():
            flash("Too many failed attempts. Wait a few minutes and try again.", "error")
            return render_template("auth/login.html", email=email), 429

        user = query(
            """SELECT id, fullname, password, role, status
                 FROM users WHERE email = %s""", (email,), one=True)

        if not user or not check_password_hash(user["password"], password):
            record_failure()
            flash("Email or password is incorrect.", "error")
            return render_template("auth/login.html", email=email), 401

        if user["status"] == "blocked":
            flash("This account has been blocked. Contact the administrator.", "error")
            return render_template("auth/login.html", email=email), 403

        clear_failures()
        sign_in(user)
        flash(f"Signed in as {user['fullname']}.", "success")

        nxt = request.args.get("next")
        if nxt and nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect(dashboard_for(user["role"]))

    return render_template("auth/login.html", email=email)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("auth.login"))
