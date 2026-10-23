"""The page an invited stranger lands on.

An invitation email used to drop somebody straight onto the signup form. That
asks a person who has never heard of the site to hand over a password before
they know what the place is, and most of them simply close the tab.

So the link opens here instead: who invited them, to what team, what the
platform actually does, and only then the button. Signing up from this page
puts them on the team outright, because by that point they have read the
invitation and clicked Join — a third confirmation on arrival is noise.

Everything here is public. The token is the only credential, which is why it
is long, expires, and names neither the team nor the address until it is
looked up.
"""
from flask import (Blueprint, current_app, flash, g, redirect,
                   render_template, url_for)

import invitations
from db import query
from workflow import notify, receipt

invites_bp = Blueprint("invites", __name__, url_prefix="/invite")


def _state(token):
    """The invitation, plus who is looking at it.

    Returns (row, problem). A problem is a sentence to show the visitor; the
    row may still be present with one, because 'this is yours but you are
    signed in as somebody else' is worth saying precisely.
    """
    row = invitations.by_token(token)
    if not row:
        return None, "That invitation link is not one we recognise."
    if row["status"] == "cancelled":
        return row, "That invitation was withdrawn by the person who sent it."
    if row["status"] == "accepted":
        return row, "That invitation has already been used."
    if not invitations.live(row):
        return row, "That invitation has expired."
    return row, None


@invites_bp.route("/<token>")
def landing(token):
    row, problem = _state(token)

    # Dead links get the same page, not a 404. Somebody arriving from a real
    # email that sat too long in an inbox should be told what happened and
    # given a way in, not shown an error.
    if problem:
        return render_template("public/invite.html", invite=row,
                               problem=problem, account=None,
                               valid_days=invitations.INVITE_VALID_DAYS,
                               signed_in_as=g.get("user")), 410 if row else 404

    ok, why = invitations.team_open(row["team_id"])
    if not ok:
        return render_template("public/invite.html", invite=row, problem=why,
                               account=None, signed_in_as=g.get("user"),
                               valid_days=invitations.INVITE_VALID_DAYS)

    # Does this address already have an account? Changes the offer from
    # "create one" to "sign in", and saves them discovering it the hard way
    # on a signup form that rejects their email.
    account = query("SELECT id, role FROM users WHERE LOWER(email)=%s",
                    (row["email"],), one=True)

    return render_template("public/invite.html", invite=row, problem=None,
                           account=account, signed_in_as=g.get("user"),
                           valid_days=invitations.INVITE_VALID_DAYS)


@invites_bp.route("/<token>/join", methods=["POST"])
def join(token):
    """For somebody who already has an account and is signed in.

    The signup path joins through claim_for instead. This is the other half:
    the invited address turned out to be registered already, so there is no
    account to create, only a seat to take.
    """
    row, problem = _state(token)
    if problem:
        flash(problem, "error")
        return redirect(url_for("invites.landing", token=token))

    me = g.get("user")
    if not me:
        return redirect(url_for("auth.login", next=url_for("invites.landing",
                                                           token=token)))

    # The token is not a transferable pass. It was sent to one address and
    # only that address can spend it, however it got forwarded.
    if me["email"].lower() != row["email"]:
        flash(f"This invitation was sent to {row['email']}. You are signed in "
              f"as {me['email']} — sign out and back in with the invited "
              f"address, or ask for a fresh invitation.", "error")
        return redirect(url_for("invites.landing", token=token))

    if me["role"] != "student":
        flash("Only student accounts can join a team.", "error")
        return redirect(url_for("invites.landing", token=token))

    ok, why = invitations.team_open(row["team_id"])
    if not ok:
        flash(why, "error")
        return redirect(url_for("invites.landing", token=token))

    invitations.place(row, me["id"], "active")

    notify(row["invited_by"],
           f"{me['fullname']} has joined your team \"{row['team_name']}\".",
           url_for("teams.detail", team_id=row["team_id"]))
    receipt(me["id"], f"You joined {row['team_name']}",
            f"You are now a member of \"{row['team_name']}\" on "
            f"{current_app.config['BRAND']}. The team applies for briefs as "
            f"one, and when a company accepts it you each get your own "
            f"placement under the same team.",
            url_for("teams.detail", team_id=row["team_id"]))

    flash(f"You have joined \"{row['team_name']}\".", "success")
    return redirect(url_for("teams.detail", team_id=row["team_id"]))
