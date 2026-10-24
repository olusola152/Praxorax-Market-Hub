"""A student and their supervising lecturer, talking about a placement.

Scoped to an assignment rather than being a general inbox. The two of them
only have a reason to talk because of a specific piece of work, and tying
every thread to one means a lecturer's list of conversations is the list of
placements they already supervise, not a second thing to keep up with.

Only the two people on a placement can read it. Not the company, whose
relationship is with the finished work rather than the working out; not the
university, which sees the review chain; not an administrator, who can see
that a thread exists but has no business reading it. A student asking their
supervisor a question they are embarrassed by should be able to.
"""
from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

import social
from auth_utils import login_required
from db import execute, query, scalar
from workflow import notify

messages_bp = Blueprint("messages", __name__, url_prefix="/messages")

MAX_BODY = 4000


def _placement(assignment_id):
    """The placement, if the signed-in person is one of its two parties."""
    row = query(
        """SELECT a.id, a.student_id, a.lecturer_id, a.status,
                  p.title, p.id AS project_id,
                  stu.fullname AS student_name, stu.links_public AS student_links,
                  lec.fullname AS lecturer_name, lec.links_public AS lecturer_links,
                  co.name AS company_name
             FROM assignments a
             JOIN projects p   ON p.id = a.project_id
             JOIN users stu    ON stu.id = a.student_id
             LEFT JOIN users lec ON lec.id = a.lecturer_id
             LEFT JOIN companies co ON co.id = p.company_id
            WHERE a.id = %s""", (assignment_id,), one=True)
    if not row:
        abort(404)

    me = g.user["id"]
    if me not in (row["student_id"], row["lecturer_id"]):
        # 404 rather than 403: whether a particular placement exists is not
        # something somebody outside it should be able to probe for.
        abort(404)
    return row


def _other_party(row):
    if g.user["id"] == row["student_id"]:
        return (row["lecturer_id"], row["lecturer_name"], row["lecturer_links"])
    return (row["student_id"], row["student_name"], row["student_links"])


def unread_for(user_id):
    """Messages waiting, across every placement this person is on.

    Runs on every page render through the context processor, which is why it
    is one indexed count rather than a join per thread.
    """
    return scalar(
        """SELECT COUNT(*) FROM messages m
             JOIN assignments a ON a.id = m.assignment_id
            WHERE m.read_at IS NULL AND m.sender_id <> %s
              AND (a.student_id = %s OR a.lecturer_id = %s)""",
        (user_id, user_id, user_id)) or 0


@messages_bp.route("/")
@login_required
def index():
    """Every thread this person is part of."""
    if g.user["role"] not in ("student", "lecturer"):
        flash("Supervision threads are between a student and their "
              "supervising lecturer.", "error")
        return redirect(url_for("home"))

    # Wrapped in an outer select because Postgres will take a bare output
    # name in ORDER BY but not one inside an expression, and the ordering
    # wants COALESCE(last_at, assigned_at) — a thread with nothing in it yet
    # should sort by when the placement began rather than fall to the bottom.
    threads = query(
        """SELECT * FROM (
             SELECT a.id, a.assigned_at, p.title, co.name AS company_name,
                    stu.fullname AS student_name,
                    lec.fullname AS lecturer_name,
                    (SELECT COUNT(*) FROM messages m
                      WHERE m.assignment_id = a.id) AS total,
                    (SELECT COUNT(*) FROM messages m
                      WHERE m.assignment_id = a.id AND m.read_at IS NULL
                        AND m.sender_id <> %s) AS unread,
                    (SELECT MAX(sent_at) FROM messages m
                      WHERE m.assignment_id = a.id) AS last_at
               FROM assignments a
               JOIN projects p ON p.id = a.project_id
               JOIN users stu ON stu.id = a.student_id
               LEFT JOIN users lec ON lec.id = a.lecturer_id
               LEFT JOIN companies co ON co.id = p.company_id
              WHERE (a.student_id = %s OR a.lecturer_id = %s)
                AND a.lecturer_id IS NOT NULL
           ) t
           ORDER BY t.unread DESC, COALESCE(t.last_at, t.assigned_at) DESC""",
        (g.user["id"], g.user["id"], g.user["id"]))

    return render_template("shared/threads.html", threads=threads,
                           is_student=g.user["role"] == "student")


@messages_bp.route("/<int:assignment_id>", methods=["GET", "POST"])
@login_required
def thread(assignment_id):
    row = _placement(assignment_id)
    other_id, other_name, other_links = _other_party(row)

    if not row["lecturer_id"]:
        flash("This placement has no supervising lecturer, so there is "
              "nobody to message here.", "error")
        return redirect(url_for("messages.index"))

    if request.method == "POST":
        body = (request.form.get("body") or "").strip()
        if not body:
            flash("Write something first.", "error")
            return redirect(url_for("messages.thread", assignment_id=assignment_id))
        if len(body) > MAX_BODY:
            flash(f"That is longer than {MAX_BODY} characters. Please shorten it.",
                  "error")
            return redirect(url_for("messages.thread", assignment_id=assignment_id))

        execute("""INSERT INTO messages (assignment_id, sender_id, body)
                   VALUES (%s,%s,%s)""", (assignment_id, g.user["id"], body))

        # One alert per message, which is the point of a message. notify()
        # already respects the person's email switch and never fails the
        # write if mail is down.
        notify(other_id,
               f"{g.user['fullname']} sent you a message about "
               f"\"{row['title']}\".",
               url_for("messages.thread", assignment_id=assignment_id))

        return redirect(url_for("messages.thread", assignment_id=assignment_id))

    # Opening the thread is reading it. Only the other person's messages are
    # marked — your own were never unread.
    execute("""UPDATE messages SET read_at=NOW()
                WHERE assignment_id=%s AND sender_id<>%s AND read_at IS NULL""",
            (assignment_id, g.user["id"]))

    msgs = query(
        """SELECT m.*, u.fullname, u.role
             FROM messages m JOIN users u ON u.id = m.sender_id
            WHERE m.assignment_id = %s ORDER BY m.sent_at""",
        (assignment_id,))

    # Their outside handles, but only if they chose to show them. A thread
    # here is the private channel; these are an extra the other person
    # opted into, not a directory.
    outside = social.links_for(other_id, contactable_only=True) if other_links else []

    return render_template("shared/thread.html", placement=row, msgs=msgs,
                           other_name=other_name, outside=outside,
                           me=g.user["id"])
