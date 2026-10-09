"""Per-account settings that every role shares.

Right now that is one switch: whether alerts are also emailed. It lives in its
own blueprint because each role has its own profile page, and a preference
about email has nothing to do with being a lecturer or a company.
"""
from flask import Blueprint, flash, g, redirect, request, url_for

import mailer
from auth_utils import login_required
from db import execute

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


@settings_bp.post("/email-alerts")
@login_required
def email_alerts():
    wanted = request.form.get("email_notifications") == "on"
    execute("UPDATE users SET email_notifications=%s WHERE id=%s",
            (wanted, g.user["id"]))

    if wanted and not mailer.configured():
        flash("Saved — but email is not switched on for this site yet, so "
              "nothing will be sent until an administrator configures it.",
              "success")
    elif wanted:
        flash("You will get an email whenever something needs your attention.",
              "success")
    else:
        flash("Email alerts off. They will still appear here in the app.",
              "success")

    return redirect(request.referrer or url_for("home"))
