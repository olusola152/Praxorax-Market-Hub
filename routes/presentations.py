"""Presentation routes — proposing a slot, agreeing one, and the room itself.

The shape of this on purpose: every page here is reachable by all four roles
and shows the same facts, because a student, a lecturer and a company arguing
over when a defence happened is exactly the dispute this record settles. What
differs by role is which buttons are on the page, and that is decided by the
permission helpers in presentations.py rather than by the templates.
"""
from datetime import timedelta

from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, url_for)

import presentations as pres
from auth_utils import log_action, login_required
from workflow import notify

presentations_bp = Blueprint("presentations", __name__, url_prefix="/presentations")

MAX_AHEAD = timedelta(days=120)


def _chain_or_404(assignment_id):
    chain = pres.chain_for(assignment_id)
    if not chain:
        abort(404)
    return chain


def _load(presentation_id):
    """The session, the signed-in person's place in it, or a refusal."""
    row = pres.get(presentation_id)
    if not row:
        abort(404)
    part = pres.my_part(presentation_id, g.user["id"])
    if not pres.may_view(g.user, row, part):
        abort(403)
    return row, part


def _shell():
    """Administrators stay inside the dark deck; everyone else gets the paper.

    Returned as template variables rather than branched on in the templates,
    so there is one presentation page rather than an admin copy drifting out
    of step with it.
    """
    if g.user["role"] == "admin":
        return {"shell": "admin/_shell_plain.html", "deck": True}
    return {"shell": "base.html", "deck": False}


def _others(presentation_id, exclude_id):
    return [a["user_id"] for a in pres.attendees(presentation_id)
            if a["user_id"] != exclude_id]


# ------------------------------------------------------------------ my list

@presentations_bp.route("/")
@login_required
def index():
    """Everything the signed-in person is invited to — or, for the two roles
    that oversee rather than attend, everything they are answerable for."""
    role = g.user["role"]
    if role == "admin":
        rows, oversight = pres.for_platform(), True
    elif role == "university":
        uni = g.get("university")
        rows = pres.for_university(uni["id"]) if uni else []
        oversight = True
    else:
        rows, oversight = pres.mine(g.user["id"]), False

    return render_template("shared/presentations.html", sessions=rows,
                           oversight=oversight, helper=pres, **_shell())


# ------------------------------------------------------- one placement's set

@presentations_bp.route("/placement/<int:assignment_id>")
@login_required
def placement(assignment_id):
    chain = _chain_or_404(assignment_id)

    # Viewing is wider than proposing: the university above the lecturer sees
    # its own students' defences without being able to book one.
    allowed = pres.may_propose(g.user, chain)
    if not allowed and g.user["role"] == "university":
        uni = g.get("university")
        allowed = bool(uni and chain["university_id"] == uni["id"])
    if not allowed:
        abort(403)

    return render_template(
        "shared/presentation_placement.html", chain=chain,
        sessions=pres.for_assignment(assignment_id),
        may_propose=pres.may_propose(g.user, chain), helper=pres,
        notice_minutes=int(pres.min_notice().total_seconds() // 60), **_shell())


@presentations_bp.route("/placement/<int:assignment_id>/propose", methods=["POST"])
@login_required
def propose(assignment_id):
    chain = _chain_or_404(assignment_id)
    if not pres.may_propose(g.user, chain):
        abort(403)

    back = url_for("presentations.placement", assignment_id=assignment_id)

    if chain["assignment_status"] in ("cancelled",):
        flash("This placement was cancelled, so there is nothing to present.",
              "error")
        return redirect(back)

    title = (request.form.get("title") or "").strip()
    agenda = (request.form.get("agenda") or "").strip()
    starts_at = pres.parse_local(request.form.get("starts_at"))
    provider = request.form.get("provider") or "jitsi"

    try:
        duration = int(request.form.get("duration_mins") or 30)
    except ValueError:
        duration = 0

    errors = []
    if len(title) < 4:
        title = f"Project presentation — {chain['title']}"[:160]
    if not starts_at:
        errors.append("Pick a date and time for the session.")
    elif pres.too_soon(starts_at):
        errors.append(pres.notice_message())
    elif starts_at > pres.now() + MAX_AHEAD:
        errors.append("That is more than four months away.")
    if not 10 <= duration <= 240:
        errors.append("Length must be between 10 and 240 minutes.")

    external_url = None
    if provider == "external":
        external_url = pres.valid_external_url(request.form.get("external_url"))
        if not external_url:
            errors.append(
                "Paste a full https link to a Zoom, Teams, Meet or Whereby "
                "meeting, or leave the built-in video selected.")
    elif provider != "jitsi":
        errors.append("Pick where the call will happen.")

    if starts_at and not errors:
        other = pres.clash(assignment_id, starts_at, duration)
        if other:
            errors.append(
                f"That overlaps a session already booked for "
                f"{pres.fmt(other['starts_at'])}. Cancel that one first, or "
                f"pick another time.")

    if errors:
        for message in errors:
            flash(message, "error")
        return redirect(back)

    presentation_id = pres.create(
        assignment_id, g.user["id"], title, agenda, starts_at, duration,
        provider=provider, external_url=external_url)

    log_action("presentation_proposed", "assignment", assignment_id,
               f"{pres.fmt(starts_at)} via {provider}")

    who = g.user["fullname"]
    for user_id in _others(presentation_id, g.user["id"]):
        notify(user_id,
               f"{who} has proposed a project presentation for "
               f"\"{chain['title']}\" on {pres.fmt(starts_at)}. "
               f"Confirm the time or suggest another.",
               pres.room_url(presentation_id))

    flash("Proposed. Everyone has been told and the session is confirmed once "
          "they agree to the time.", "success")
    return redirect(url_for("presentations.room", presentation_id=presentation_id))


# --------------------------------------------------------------- one session

@presentations_bp.route("/<int:presentation_id>")
@login_required
def room(presentation_id):
    """The session page: the facts, the buttons, and the call when it is open."""
    row, part = _load(presentation_id)

    can_join, why_not = pres.join_window(row)
    joinable = can_join and part is not None

    return render_template(
        "shared/presentation_room.html", session=row, part=part,
        people=pres.attendees(presentation_id), joinable=joinable,
        why_not=why_not,
        may_decide=pres.may_decide(g.user, row, part),
        may_cancel=pres.may_cancel(g.user, row, part),
        jitsi_domain=current_app.config["JITSI_DOMAIN"], helper=pres,
        **_shell())


@presentations_bp.route("/<int:presentation_id>/join", methods=["POST"])
@login_required
def join(presentation_id):
    """Marks attendance, then hands back to the room with the call running.

    A POST because it writes. The room page loads the video only after this,
    so the attendance record cannot be dodged by sitting on the page with the
    call open.
    """
    row, part = _load(presentation_id)
    if not part:
        abort(403)

    can_join, why_not = pres.join_window(row)
    if not can_join:
        flash(why_not, "error")
        return redirect(url_for("presentations.room", presentation_id=presentation_id))

    first_in = row["status"] == "confirmed"
    pres.mark_joined(presentation_id, g.user["id"])

    if first_in:
        for user_id in _others(presentation_id, g.user["id"]):
            notify(user_id,
                   f"{g.user['fullname']} has opened the presentation room for "
                   f"\"{row['title']}\". Join now.",
                   pres.room_url(presentation_id), email=False)

    return redirect(url_for("presentations.room",
                            presentation_id=presentation_id, live=1))


@presentations_bp.route("/<int:presentation_id>/respond", methods=["POST"])
@login_required
def respond(presentation_id):
    row, part = _load(presentation_id)
    if not part:
        abort(403)
    if row["status"] not in ("proposed", "confirmed"):
        flash("That session is no longer waiting on an answer.", "error")
        return redirect(url_for("presentations.room", presentation_id=presentation_id))

    accepted = request.form.get("answer") == "accept"
    reason = (request.form.get("reason") or "").strip()
    result = pres.respond(presentation_id, g.user["id"], accepted, reason)

    who = g.user["fullname"]
    if result == "cancelled":
        body = (f"{who} cannot make the presentation on "
                f"{pres.fmt(row['starts_at'])} for \"{row['title']}\"."
                + (f" Reason: {reason}" if reason else "")
                + " Propose another time.")
        flash("Declined. Everyone has been told, and the slot is free again.",
              "success")
    elif result == "confirmed":
        body = (f"The presentation for \"{row['title']}\" is confirmed for "
                f"{pres.fmt(row['starts_at'])}. The room opens 20 minutes "
                f"before.")
        flash("Confirmed. Everyone has agreed, so the session is set.", "success")
    else:
        body = (f"{who} has accepted the presentation time for "
                f"\"{row['title']}\" on {pres.fmt(row['starts_at'])}.")
        flash("Noted. The session is confirmed once everyone else agrees.",
              "success")

    for user_id in _others(presentation_id, g.user["id"]):
        notify(user_id, body, pres.room_url(presentation_id))

    log_action(f"presentation_{result}", "presentation", presentation_id, reason or None)
    return redirect(url_for("presentations.room", presentation_id=presentation_id))


@presentations_bp.route("/<int:presentation_id>/reschedule", methods=["POST"])
@login_required
def reschedule(presentation_id):
    row, part = _load(presentation_id)
    if not (part or g.user["role"] == "admin"):
        abort(403)
    if row["status"] in ("held", "missed", "cancelled"):
        flash("That session is closed. Propose a new one instead.", "error")
        return redirect(url_for("presentations.room", presentation_id=presentation_id))

    starts_at = pres.parse_local(request.form.get("starts_at"))
    try:
        duration = int(request.form.get("duration_mins") or row["duration_mins"])
    except ValueError:
        duration = 0

    errors = []
    if not starts_at:
        errors.append("Pick a new date and time.")
    elif pres.too_soon(starts_at):
        errors.append(pres.notice_message())
    elif starts_at > pres.now() + MAX_AHEAD:
        errors.append("That is more than four months away.")
    if not 10 <= duration <= 240:
        errors.append("Length must be between 10 and 240 minutes.")
    if starts_at and not errors:
        other = pres.clash(row["assignment_id"], starts_at, duration,
                           ignore_id=presentation_id)
        if other:
            errors.append("That overlaps another session on this placement.")

    if errors:
        for message in errors:
            flash(message, "error")
        return redirect(url_for("presentations.room", presentation_id=presentation_id))

    pres.reschedule(presentation_id, starts_at, duration, g.user["id"])
    log_action("presentation_rescheduled", "presentation", presentation_id,
               pres.fmt(starts_at))

    for user_id in _others(presentation_id, g.user["id"]):
        notify(user_id,
               f"{g.user['fullname']} has moved the presentation for "
               f"\"{row['title']}\" to {pres.fmt(starts_at)}. "
               f"Confirm the new time.",
               pres.room_url(presentation_id))

    flash("Moved. Everyone has been asked to agree to the new time.", "success")
    return redirect(url_for("presentations.room", presentation_id=presentation_id))


@presentations_bp.route("/<int:presentation_id>/outcome", methods=["POST"])
@login_required
def outcome(presentation_id):
    """What the company decided. The one write only the company may make."""
    row, part = _load(presentation_id)
    if not pres.may_decide(g.user, row, part):
        abort(403)
    if row["status"] in ("held", "cancelled"):
        flash("The outcome of that session is already recorded.", "error")
        return redirect(url_for("presentations.room", presentation_id=presentation_id))

    verdict = request.form.get("outcome")
    notes = (request.form.get("outcome_notes") or "").strip()

    if verdict == "missed":
        pres.mark_missed(presentation_id, notes, g.user["id"])
        body = (f"The presentation for \"{row['title']}\" on "
                f"{pres.fmt(row['starts_at'])} was marked as not held."
                + (f" {notes}" if notes else ""))
        flash("Recorded as not held.", "success")
    elif verdict in ("passed", "rework", "undecided"):
        pres.record_outcome(presentation_id, verdict, notes, g.user["id"])
        body = (f"{row['company_name']} has recorded the outcome of your "
                f"presentation for \"{row['title']}\": "
                f"{pres.OUTCOME_LABEL[verdict]}."
                + (f" {notes}" if notes else ""))
        flash("Outcome saved. Everyone on the placement has been told.",
              "success")
    else:
        flash("Pick an outcome.", "error")
        return redirect(url_for("presentations.room", presentation_id=presentation_id))

    log_action("presentation_outcome", "presentation", presentation_id, verdict)
    for user_id in _others(presentation_id, g.user["id"]):
        notify(user_id, body, pres.room_url(presentation_id))

    return redirect(url_for("presentations.room", presentation_id=presentation_id))


@presentations_bp.route("/<int:presentation_id>/cancel", methods=["POST"])
@login_required
def cancel(presentation_id):
    row, part = _load(presentation_id)
    if not pres.may_cancel(g.user, row, part):
        abort(403)
    if row["status"] in ("held", "missed", "cancelled"):
        flash("That session is already closed.", "error")
        return redirect(url_for("presentations.room", presentation_id=presentation_id))

    reason = (request.form.get("reason") or "").strip()
    pres.cancel(presentation_id, reason)
    log_action("presentation_cancelled", "presentation", presentation_id, reason or None)

    for user_id in _others(presentation_id, g.user["id"]):
        notify(user_id,
               f"{g.user['fullname']} has cancelled the presentation for "
               f"\"{row['title']}\" on {pres.fmt(row['starts_at'])}."
               + (f" Reason: {reason}" if reason else ""),
               pres.room_url(presentation_id))

    flash("Cancelled.", "success")
    return redirect(url_for("presentations.room", presentation_id=presentation_id))
