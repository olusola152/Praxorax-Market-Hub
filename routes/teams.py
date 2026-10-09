"""Teams.

Students group up before applying for a brief. One person creates the team and
becomes its lead; everyone else joins by invitation. A team applies as a unit,
and when a company accepts it, every active member gets their own placement row
tied to the same team, so the existing review chain keeps working unchanged.

Only students can be in a team. An invitation goes to an email address that
already belongs to a student account — there is no invite-a-stranger flow,
because an account has to exist before it can be placed on a project.
"""
from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

from auth_utils import role_required
from db import execute, get_db, query, scalar
from workflow import notify

teams_bp = Blueprint("teams", __name__, url_prefix="/teams")

MAX_MEMBERS = 6


def team_for(team_id, must_lead=False):
    """Load a team the signed-in student actually belongs to."""
    row = query(
        """SELECT t.*, u.fullname AS lead_name, p.title AS project_title
             FROM teams t
             JOIN users u ON u.id = t.created_by
             LEFT JOIN projects p ON p.id = t.project_id
            WHERE t.id = %s""", (team_id,), one=True)
    if not row:
        abort(404)

    me = query(
        "SELECT * FROM team_members WHERE team_id=%s AND user_id=%s",
        (team_id, g.user["id"]), one=True)
    if not me or me["status"] not in ("active", "invited"):
        abort(403)
    if must_lead and me["role"] != "lead":
        abort(403)

    row["me"] = me
    return row


def members_of(team_id, active_only=False):
    sql = """SELECT tm.*, u.fullname, u.email, sp.department, sp.level
               FROM team_members tm
               JOIN users u ON u.id = tm.user_id
               LEFT JOIN student_profiles sp ON sp.user_id = u.id
              WHERE tm.team_id = %s"""
    if active_only:
        sql += " AND tm.status = 'active'"
    sql += " ORDER BY (tm.role='lead') DESC, tm.invited_at"
    return query(sql, (team_id,))


def active_member_ids(team_id):
    return [r["user_id"] for r in query(
        "SELECT user_id FROM team_members WHERE team_id=%s AND status='active'",
        (team_id,))]


@teams_bp.route("/")
@role_required("student")
def index():
    mine = query(
        """SELECT t.*, tm.role AS my_role, p.title AS project_title,
                  (SELECT COUNT(*) FROM team_members m
                    WHERE m.team_id=t.id AND m.status='active') AS member_count
             FROM teams t
             JOIN team_members tm ON tm.team_id = t.id
             LEFT JOIN projects p ON p.id = t.project_id
            WHERE tm.user_id=%s AND tm.status='active'
            ORDER BY t.created_at DESC""", (g.user["id"],))

    invites = query(
        """SELECT tm.id AS membership_id, t.id AS team_id, t.name,
                  u.fullname AS invited_by, tm.invited_at
             FROM team_members tm
             JOIN teams t ON t.id = tm.team_id
             JOIN users u ON u.id = t.created_by
            WHERE tm.user_id=%s AND tm.status='invited'
            ORDER BY tm.invited_at DESC""", (g.user["id"],))

    return render_template("student/teams.html", teams=mine, invites=invites)


@teams_bp.route("/new", methods=["POST"])
@role_required("student")
def create():
    name = request.form.get("name", "").strip()
    if len(name) < 3:
        flash("Give the team a name of at least 3 characters.", "error")
        return redirect(url_for("teams.index"))

    leading = scalar(
        """SELECT COUNT(*) FROM team_members tm JOIN teams t ON t.id=tm.team_id
            WHERE tm.user_id=%s AND tm.role='lead' AND tm.status='active'
              AND t.status <> 'disbanded'""", (g.user["id"],))
    if leading >= 3:
        flash("You already lead three teams. Wind one up before starting another.",
              "error")
        return redirect(url_for("teams.index"))

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO teams (name, created_by) VALUES (%s,%s) RETURNING id",
                (name, g.user["id"]))
            team_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO team_members (team_id, user_id, role, status, joined_at)
                   VALUES (%s,%s,'lead','active',NOW())""", (team_id, g.user["id"]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    flash(f"{name} created. Invite the people you want on it.", "success")
    return redirect(url_for("teams.detail", team_id=team_id))


@teams_bp.route("/<int:team_id>")
@role_required("student")
def detail(team_id):
    team = team_for(team_id)
    return render_template(
        "student/team_detail.html", team=team, members=members_of(team_id),
        max_members=MAX_MEMBERS,
        placements=query(
            """SELECT a.id, u.fullname FROM assignments a
                 JOIN users u ON u.id = a.student_id
                WHERE a.team_id=%s""", (team_id,)))


@teams_bp.route("/<int:team_id>/invite", methods=["POST"])
@role_required("student")
def invite(team_id):
    team = team_for(team_id, must_lead=True)
    if team["status"] not in ("forming", "applied"):
        flash("This team is already on a brief — its membership is fixed.", "error")
        return redirect(url_for("teams.detail", team_id=team_id))

    email = request.form.get("email", "").strip().lower()
    person = query(
        "SELECT id, fullname, role FROM users WHERE email=%s AND status='active'",
        (email,), one=True)

    if not person:
        flash("No account here uses that email. Ask them to sign up first.", "error")
        return redirect(url_for("teams.detail", team_id=team_id))
    if person["role"] != "student":
        flash("Only students can join a team.", "error")
        return redirect(url_for("teams.detail", team_id=team_id))
    if person["id"] == g.user["id"]:
        flash("You are already on this team.", "error")
        return redirect(url_for("teams.detail", team_id=team_id))

    count = scalar(
        """SELECT COUNT(*) FROM team_members WHERE team_id=%s
            AND status IN ('active','invited')""", (team_id,))
    if count >= MAX_MEMBERS:
        flash(f"A team tops out at {MAX_MEMBERS} people.", "error")
        return redirect(url_for("teams.detail", team_id=team_id))

    existing = query(
        "SELECT status FROM team_members WHERE team_id=%s AND user_id=%s",
        (team_id, person["id"]), one=True)
    if existing and existing["status"] in ("active", "invited"):
        flash(f"{person['fullname']} has already been asked.", "error")
        return redirect(url_for("teams.detail", team_id=team_id))

    if existing:
        execute(
            """UPDATE team_members SET status='invited', invited_at=NOW(),
                      joined_at=NULL
                WHERE team_id=%s AND user_id=%s""", (team_id, person["id"]))
    else:
        execute(
            "INSERT INTO team_members (team_id, user_id) VALUES (%s,%s)",
            (team_id, person["id"]))

    notify(person["id"],
           f"{g.user['fullname']} invited you to join the team \"{team['name']}\".",
           url_for("teams.index"))
    flash(f"Invitation sent to {person['fullname']}.", "success")
    return redirect(url_for("teams.detail", team_id=team_id))


@teams_bp.route("/invites/<int:membership_id>/<decision>", methods=["POST"])
@role_required("student")
def respond(membership_id, decision):
    if decision not in ("accept", "decline"):
        abort(400)

    row = query(
        """SELECT tm.*, t.name, t.created_by, t.status AS team_status
             FROM team_members tm JOIN teams t ON t.id = tm.team_id
            WHERE tm.id=%s AND tm.user_id=%s""",
        (membership_id, g.user["id"]), one=True)
    if not row:
        abort(404)
    if row["status"] != "invited":
        flash("That invitation is no longer open.", "error")
        return redirect(url_for("teams.index"))

    if decision == "decline":
        execute("UPDATE team_members SET status='declined' WHERE id=%s",
                (membership_id,))
        notify(row["created_by"],
               f"{g.user['fullname']} declined the invitation to \"{row['name']}\".",
               url_for("teams.detail", team_id=row["team_id"]))
        flash("Invitation declined.", "success")
        return redirect(url_for("teams.index"))

    if row["team_status"] not in ("forming", "applied"):
        flash("That team has already started work.", "error")
        return redirect(url_for("teams.index"))

    execute("UPDATE team_members SET status='active', joined_at=NOW() WHERE id=%s",
            (membership_id,))
    notify(row["created_by"],
           f"{g.user['fullname']} joined \"{row['name']}\".",
           url_for("teams.detail", team_id=row["team_id"]))
    flash(f"You are on {row['name']}.", "success")
    return redirect(url_for("teams.detail", team_id=row["team_id"]))


@teams_bp.route("/<int:team_id>/members/<int:user_id>/remove", methods=["POST"])
@role_required("student")
def remove(team_id, user_id):
    team = team_for(team_id, must_lead=True)
    if user_id == g.user["id"]:
        flash("A lead cannot remove themselves. Disband the team instead.", "error")
        return redirect(url_for("teams.detail", team_id=team_id))
    if team["status"] not in ("forming", "applied"):
        flash("Membership is fixed once a team is placed on a brief.", "error")
        return redirect(url_for("teams.detail", team_id=team_id))

    execute(
        """UPDATE team_members SET status='removed'
            WHERE team_id=%s AND user_id=%s AND status IN ('active','invited')""",
        (team_id, user_id))
    notify(user_id, f"You were removed from the team \"{team['name']}\".",
           url_for("teams.index"))
    flash("Removed.", "success")
    return redirect(url_for("teams.detail", team_id=team_id))


@teams_bp.route("/<int:team_id>/leave", methods=["POST"])
@role_required("student")
def leave(team_id):
    team = team_for(team_id)
    if team["me"]["role"] == "lead":
        flash("You lead this team. Disband it, or hand the lead over first.",
              "error")
        return redirect(url_for("teams.detail", team_id=team_id))
    if team["status"] not in ("forming", "applied"):
        flash("You cannot leave a team that is already working on a brief.", "error")
        return redirect(url_for("teams.detail", team_id=team_id))

    execute("UPDATE team_members SET status='removed' WHERE team_id=%s AND user_id=%s",
            (team_id, g.user["id"]))
    notify(team["created_by"],
           f"{g.user['fullname']} left \"{team['name']}\".",
           url_for("teams.detail", team_id=team_id))
    flash("You left the team.", "success")
    return redirect(url_for("teams.index"))


@teams_bp.route("/<int:team_id>/disband", methods=["POST"])
@role_required("student")
def disband(team_id):
    team = team_for(team_id, must_lead=True)
    if team["status"] == "active":
        flash("This team is on a live brief and cannot be disbanded.", "error")
        return redirect(url_for("teams.detail", team_id=team_id))

    for uid in active_member_ids(team_id):
        if uid != g.user["id"]:
            notify(uid, f"\"{team['name']}\" was disbanded by its lead.",
                   url_for("teams.index"))

    execute("UPDATE teams SET status='disbanded' WHERE id=%s", (team_id,))
    execute("""UPDATE team_members SET status='removed'
                WHERE team_id=%s AND status IN ('active','invited')""", (team_id,))
    flash(f"{team['name']} disbanded.", "success")
    return redirect(url_for("teams.index"))
