"""Per-account settings that every role shares.

Right now that is one switch: whether alerts are also emailed. It lives in its
own blueprint because each role has its own profile page, and a preference
about email has nothing to do with being a lecturer or a company.
"""
import time

from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)

import mailer
from auth_utils import login_required
from db import execute

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


def _shell():
    """Administrators stay inside the dark deck; everyone else gets paper.

    Same arrangement the presentation pages use, so a shared page is one
    template rather than an admin copy drifting out of step with it.
    """
    if g.user["role"] == "admin":
        return {"shell": "admin/_shell_plain.html", "deck": True}
    return {"shell": "base.html", "deck": False}


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


# One test message a minute per session. Enough to try a fix and check it,
# not enough to use someone else's inbox as a target.
TEST_EVERY_SECONDS = 60


@settings_bp.post("/test-email")
@login_required
def test_email():
    """Send this account one message now and report what actually happened.

    The switch on the alerts page says email is on; it cannot say whether a
    message would arrive. A client reported exactly that gap — the setting
    looked right and nothing turned up — so this closes it by sending on the
    spot and showing the server's own answer rather than a reassurance.
    """
    last = session.get("test_email_at", 0)
    waited = time.time() - last
    if waited < TEST_EVERY_SECONDS:
        flash(f"Just sent one. Try again in "
              f"{int(TEST_EVERY_SECONDS - waited)} seconds.", "error")
        return redirect(request.referrer or url_for("home"))
    session["test_email_at"] = time.time()

    app = current_app._get_current_object()
    brand = app.config["BRAND"]
    sent, detail = mailer.send_now(
        app, g.user["email"], g.user["fullname"],
        f"Test message from {brand}",
        f"This is a test, sent because you asked for one from your alerts "
        f"page. If it reached you, {brand} can email this address and your "
        f"alerts will arrive the same way.")

    if sent:
        flash(f"Sent to {g.user['email']}. If it is not in your inbox within "
              f"a minute or two, check the spam folder — that is where a new "
              f"sending address usually lands first.", "success")
    else:
        flash(f"Could not send: {detail}", "error")

    # Links inside every email are built from BASE_URL, so a message that
    # arrives from a misconfigured site is still useless. Say so here rather
    # than letting someone conclude email works when the links do not.
    base = app.config.get("BASE_URL", "")
    if sent and ("127.0.0.1" in base or "localhost" in base):
        flash(f"Note: this site's address is set to {base}, so links inside "
              f"its emails point at a machine other people cannot reach. An "
              f"administrator should set BASE_URL to the real address.",
              "error")

    return redirect(request.referrer or url_for("home"))


@settings_bp.route("/links", methods=["GET", "POST"])
@login_required
def links():
    """Somebody's own social accounts.

    Here rather than on each role's profile page because the three profile
    pages are different templates and this is the same for all of them —
    which is the reason this blueprint exists.
    """
    import social
    from db import query

    bad = []
    if request.method == "POST":
        bad = social.save(g.user["id"], request.form)
        execute("UPDATE users SET links_public=%s WHERE id=%s",
                (request.form.get("links_public") == "on", g.user["id"]))
        if bad:
            flash("Saved, except " + ", ".join(
                social.NETWORKS[k]["label"] for k in bad) +
                " — check what you pasted there.", "error")
        else:
            flash("Your contact details are saved.", "success")
            return redirect(url_for("settings.links"))

    me = query("SELECT links_public FROM users WHERE id=%s",
               (g.user["id"],), one=True)
    return render_template("shared/links.html", **_shell(),
                           networks=social.NETWORKS,
                           blurb_for=social.blurb_for,
                           groups=social.groups_for_role(g.user["role"]),
                           handles=social.handles_for(g.user["id"]),
                           links_public=me["links_public"] if me else False,
                           bad=bad)
