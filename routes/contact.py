"""The platform's own contact page, and the feedback survey behind it.

Two things that belong together: where to find PraxoraX, and how to tell it
what is wrong with it. Both are public — a visitor who has not signed up is
exactly the person whose complaint is worth hearing, and making them make an
account first is how you never hear it.
"""
from flask import (Blueprint, current_app, flash, g, redirect,
                   render_template, request, url_for)

import mailer
import social
from db import execute, query
from workflow import notify_many

contact_bp = Blueprint("contact", __name__)

RATING_WORDS = {1: "Poor", 2: "Not great", 3: "Fine", 4: "Good", 5: "Excellent"}

MAX_TEXT = 4000


@contact_bp.route("/contact")
def index():
    return render_template("public/contact.html",
                           links=social.links_for(None),
                           networks=social.NETWORKS)


@contact_bp.route("/feedback", methods=["GET", "POST"])
def feedback():
    """The survey. A rating, what is missing, and a suggestion.

    Open to anyone, signed in or not. The rating is the only required field:
    asking for three paragraphs is how a feedback form collects nothing.
    """
    form = {"rating": "", "missing": "", "suggestion": "", "reply_to": ""}
    if g.get("user"):
        form["reply_to"] = g.user["email"]

    if request.method == "POST":
        form = {k: (request.form.get(k) or "").strip() for k in form}
        errors = []

        rating = form["rating"]
        if not rating.isdigit() or not 1 <= int(rating) <= 5:
            errors.append("Choose a rating from one to five stars.")

        if len(form["missing"]) > MAX_TEXT or len(form["suggestion"]) > MAX_TEXT:
            errors.append("That is longer than this form can take — "
                          "please shorten it.")

        reply_to = form["reply_to"]
        if reply_to and ("@" not in reply_to or len(reply_to) > 150):
            errors.append("That email address does not look right. Leave it "
                          "blank if you would rather not hear back.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("public/feedback.html", form=form,
                                   words=RATING_WORDS)

        user_id = g.user["id"] if g.get("user") else None
        row_id = execute(
            """INSERT INTO feedback (user_id, reply_to, rating, missing,
                                     suggestion, page)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (user_id, reply_to or None, int(rating),
             form["missing"] or None, form["suggestion"] or None,
             request.referrer), returning=True)

        _tell_the_team(row_id, int(rating), form, reply_to, user_id)

        flash("Thank you — that has reached us. If you left an address we "
              "will reply when there is something to say.", "success")
        return redirect(url_for("contact.feedback_thanks"))

    return render_template("public/feedback.html", form=form,
                           words=RATING_WORDS)


@contact_bp.route("/feedback/thanks")
def feedback_thanks():
    return render_template("public/feedback_thanks.html")


def _tell_the_team(row_id, rating, form, reply_to, user_id):
    """Put it in front of an administrator, in the app and by email.

    The database row is already written by the time this runs, so nothing
    here can lose a piece of feedback. Mail being down means an unread row
    on the deck rather than a complaint that evaporated.
    """
    who = "somebody signed in" if user_id else "a visitor"
    if g.get("user"):
        who = f"{g.user['fullname']} ({g.user['role']})"

    admins = query("SELECT id FROM users WHERE role='admin' AND status='active'")
    notify_many([a["id"] for a in admins],
                f"New feedback: {rating} star{'' if rating == 1 else 's'} "
                f"from {who}.",
                url_for("admin.feedback"))

    # Also to the address on the site, because an administrator who has not
    # signed in this week should still hear about a one-star review.
    to = (current_app.config.get("CONTACT_EMAIL")
          or current_app.config.get("MAIL_REPLY_TO")
          or current_app.config.get("MAIL_FROM"))
    if not to:
        return

    lines = [f"{rating}/5 — {RATING_WORDS.get(rating, '')}", "", f"From: {who}"]
    if reply_to:
        lines.append(f"Reply to: {reply_to}")
    if form["missing"]:
        lines += ["", "What is missing or not working:", form["missing"]]
    if form["suggestion"]:
        lines += ["", "Suggestion:", form["suggestion"]]

    mailer.send(to, None,
                f"{rating}-star feedback on {current_app.config['BRAND']}",
                "\n".join(lines), url_for("admin.feedback"))
