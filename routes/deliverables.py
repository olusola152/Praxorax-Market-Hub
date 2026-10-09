"""Deliverables — the pieces of work a brief is broken into.

The four fixed phases in `milestones` still exist and still drive the progress
bars. Deliverables sit beside them: a lecturer supervising a placement, or the
company that owns the brief, writes their own named pieces of work with their
own due dates, and a student submits against one.

A deliverable is invisible to students until it is published. That is the whole
point of the draft state — it lets a supervisor draft the set, then release it.
"""
from datetime import date

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

from auth_utils import login_required, subscription_required
from db import execute, query, scalar
from workflow import notify

deliverables_bp = Blueprint("deliverables", __name__, url_prefix="/deliverables")


def _may_manage(project_id):
    """Who sets the work: the owning company, or a lecturer supervising on it."""
    user = g.user
    if user["role"] == "company":
        return bool(scalar("SELECT COUNT(*) FROM projects WHERE id=%s AND company_id=%s",
                           (project_id, user["company_id"])))
    if user["role"] == "lecturer":
        return bool(scalar(
            """SELECT COUNT(*) FROM assignments
                WHERE project_id=%s AND lecturer_id=%s AND status <> 'cancelled'""",
            (project_id, user["id"])))
    return False


def _project(project_id):
    row = query(
        """SELECT p.*, c.name AS company_name FROM projects p
             JOIN companies c ON c.id = p.company_id WHERE p.id=%s""",
        (project_id,), one=True)
    if not row:
        abort(404)
    return row


def published_for(project_id):
    """What a student is allowed to see and submit against."""
    return query(
        """SELECT * FROM deliverables
            WHERE project_id=%s AND status='published'
            ORDER BY position, due_date""", (project_id,))


@deliverables_bp.route("/project/<int:project_id>")
@login_required
@subscription_required
def manage(project_id):
    if not _may_manage(project_id):
        abort(403)

    rows = query(
        """SELECT d.*, u.fullname AS author,
                  (SELECT COUNT(*) FROM submissions s WHERE s.deliverable_id=d.id)
                    AS submission_count
             FROM deliverables d JOIN users u ON u.id = d.created_by
            WHERE d.project_id=%s ORDER BY d.position, d.created_at""",
        (project_id,))

    return render_template("shared/deliverables.html", project=_project(project_id),
                           deliverables=rows, today=date.today())


@deliverables_bp.route("/project/<int:project_id>/new", methods=["POST"])
@login_required
@subscription_required
def create(project_id):
    if not _may_manage(project_id):
        abort(403)
    project = _project(project_id)

    title = request.form.get("title", "").strip()
    due_raw = request.form.get("due_date", "")
    errors = []

    if len(title) < 4:
        errors.append("Give the deliverable a title of at least 4 characters.")
    try:
        due = date.fromisoformat(due_raw)
    except ValueError:
        due = None
        errors.append("Pick a due date.")
    if due and due < date.today():
        errors.append("The due date is in the past.")
    if due and due > project["deadline"]:
        errors.append(
            f"That falls after the brief's own deadline "
            f"({project['deadline'].strftime('%d %b %Y')}).")

    if errors:
        for message in errors:
            flash(message, "error")
        return redirect(url_for("deliverables.manage", project_id=project_id))

    position = (scalar("SELECT COALESCE(MAX(position),0) FROM deliverables WHERE project_id=%s",
                       (project_id,)) or 0) + 1
    execute(
        """INSERT INTO deliverables
           (project_id, created_by, title, description, due_date, position)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (project_id, g.user["id"], title,
         request.form.get("description") or None, due, position))

    flash("Saved as a draft. Students see nothing until you publish it.", "success")
    return redirect(url_for("deliverables.manage", project_id=project_id))


@deliverables_bp.route("/<int:deliverable_id>/<action>", methods=["POST"])
@login_required
@subscription_required
def change(deliverable_id, action):
    if action not in ("publish", "archive", "delete"):
        abort(400)

    row = query("SELECT * FROM deliverables WHERE id=%s", (deliverable_id,), one=True)
    if not row:
        abort(404)
    if not _may_manage(row["project_id"]):
        abort(403)

    if action == "delete":
        if row["status"] == "published":
            flash("A published deliverable cannot be deleted. Archive it instead.",
                  "error")
        elif scalar("SELECT COUNT(*) FROM submissions WHERE deliverable_id=%s",
                    (deliverable_id,)):
            flash("Students have already submitted against this one.", "error")
        else:
            execute("DELETE FROM deliverables WHERE id=%s", (deliverable_id,))
            flash("Deleted.", "success")

    elif action == "archive":
        execute("UPDATE deliverables SET status='archived' WHERE id=%s",
                (deliverable_id,))
        flash("Archived. Students can no longer submit against it.", "success")

    else:
        execute(
            """UPDATE deliverables SET status='published', published_at=NOW()
                WHERE id=%s""", (deliverable_id,))

        # Tell everyone currently placed on this brief.
        for person in query(
                """SELECT DISTINCT a.student_id, a.id AS assignment_id
                     FROM assignments a
                    WHERE a.project_id=%s AND a.status NOT IN ('completed','cancelled')""",
                (row["project_id"],)):
            notify(person["student_id"],
                   f"New deliverable: \"{row['title']}\", due "
                   f"{row['due_date'].strftime('%d %b %Y')}.",
                   url_for("student.work", assignment_id=person["assignment_id"]))

        flash("Published. Students can submit against it now.", "success")

    return redirect(url_for("deliverables.manage", project_id=row["project_id"]))
