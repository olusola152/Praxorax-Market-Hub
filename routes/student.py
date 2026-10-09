from datetime import date

from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, url_for)

import matching
import storage
from auth_utils import is_independent_student, role_required, subscription_required
from db import execute, get_db, query, scalar
from routes.deliverables import published_for
from workflow import (chain_people, first_stage, files_for_assignment, history,
                      notify, STAGE_LABEL, submission_files)

student_bp = Blueprint("student", __name__, url_prefix="/student")


@student_bp.route("/dashboard")
@role_required("student")
def dashboard():
    uid = g.user["id"]
    stats = {
        "available": scalar(
            "SELECT COUNT(*) FROM projects WHERE status='open' AND deadline >= CURRENT_DATE"),
        "active": scalar(
            """SELECT COUNT(*) FROM assignments
                WHERE student_id=%s AND status IN ('assigned','in_progress','revision')""",
            (uid,)),
        "completed": scalar(
            "SELECT COUNT(*) FROM assignments WHERE student_id=%s AND status='completed'",
            (uid,)),
        "certificates": scalar("SELECT COUNT(*) FROM certificates WHERE student_id=%s", (uid,)),
        "overdue": scalar(
            """SELECT COUNT(*) FROM milestones m JOIN assignments a ON a.id=m.assignment_id
                WHERE a.student_id=%s AND m.status<>'done' AND m.due_date < CURRENT_DATE""",
            (uid,)),
    }

    profile = query(
        """SELECT sp.*, f.name AS field_name, u.name AS university_name
             FROM student_profiles sp
             LEFT JOIN fields f ON f.id=sp.field_id
             LEFT JOIN universities u ON u.id=sp.university_id
            WHERE sp.user_id=%s""", (uid,), one=True) or {}

    active = query(
        """SELECT a.id, a.status, p.title, p.deadline, c.name AS company_name,
                  lec.fullname AS lecturer_name,
                  (SELECT COUNT(*) FROM milestones m
                    WHERE m.assignment_id=a.id AND m.status='done') AS done,
                  (SELECT COUNT(*) FROM milestones m WHERE m.assignment_id=a.id) AS total,
                  (SELECT stage FROM submissions s WHERE s.assignment_id=a.id
                    ORDER BY version DESC LIMIT 1) AS stage
             FROM assignments a
             JOIN projects p ON p.id=a.project_id
             JOIN companies c ON c.id=p.company_id
             LEFT JOIN users lec ON lec.id=a.lecturer_id
            WHERE a.student_id=%s AND a.status NOT IN ('completed','cancelled')
            ORDER BY p.deadline""", (uid,))

    return render_template("student/dashboard.html", stats=stats, profile=profile,
                           active=active, stage_label=STAGE_LABEL)


@student_bp.route("/notifications")
@role_required("student")
def notifications():
    rows = query(
        "SELECT * FROM notifications WHERE user_id=%s ORDER BY created_at DESC LIMIT 100",
        (g.user["id"],))
    execute("UPDATE notifications SET read_at=NOW() WHERE user_id=%s AND read_at IS NULL",
            (g.user["id"],))
    return render_template("shared/notifications.html", rows=rows)


@student_bp.route("/projects")
@role_required("student")
def browse():
    """Read-only. A lecturer decides who works on what."""
    search = request.args.get("q", "").strip()
    sql = """SELECT p.id, p.title, p.description, p.difficulty, p.deadline,
                    p.max_students, f.name AS field_name, c.name AS company_name,
                    f.image_url AS field_image, c.logo_url AS company_logo,
                    (SELECT string_agg(s.name, ', ' ORDER BY s.name)
                       FROM project_skills ps JOIN skills s ON s.id=ps.skill_id
                      WHERE ps.project_id=p.id) AS skill_list
               FROM projects p JOIN fields f ON f.id=p.field_id
               JOIN companies c ON c.id=p.company_id
              WHERE p.status='open' AND p.deadline >= CURRENT_DATE"""
    params = []
    if search:
        sql += " AND (p.title ILIKE %s OR p.description ILIKE %s)"
        params += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY p.created_at DESC"

    projects = query(sql, tuple(params))

    applied = {}
    if is_independent_student():
        applied = {r["project_id"]: r["status"] for r in query(
            """SELECT project_id, status FROM project_applications
                WHERE student_id=%s""", (g.user["id"],))}

    saved = {r["project_id"] for r in query(
        "SELECT project_id FROM bookmarks WHERE user_id=%s", (g.user["id"],))}

    matching.annotate(projects, g.user["id"])
    if request.args.get("sort") == "match":
        projects.sort(key=lambda p: p["match"] or 0, reverse=True)

    return render_template("student/projects.html", projects=projects,
                           search=search, independent=is_independent_student(),
                           applied=applied, saved=saved,
                           sort=request.args.get("sort", ""))


@student_bp.route("/projects/<int:project_id>")
@role_required("student")
def project_detail(project_id):
    project = query(
        """SELECT p.*, f.name AS field_name, c.name AS company_name, c.website,
                  f.image_url AS field_image, c.logo_url AS company_logo,
                  (SELECT string_agg(s.name, ', ' ORDER BY s.name)
                     FROM project_skills ps JOIN skills s ON s.id=ps.skill_id
                    WHERE ps.project_id=p.id) AS skill_list
             FROM projects p JOIN fields f ON f.id=p.field_id
             JOIN companies c ON c.id=p.company_id
            WHERE p.id=%s AND p.status IN ('open','engaged','completed')""",
        (project_id,), one=True)
    if not project:
        abort(404)

    application = None
    if is_independent_student():
        application = query(
            """SELECT * FROM project_applications
                WHERE project_id=%s AND student_id=%s""",
            (project_id, g.user["id"]), one=True)

    my_teams = []
    if is_independent_student():
        my_teams = query(
            """SELECT t.id, t.name,
                      (SELECT COUNT(*) FROM team_members m
                        WHERE m.team_id=t.id AND m.status='active') AS size
                 FROM teams t JOIN team_members tm ON tm.team_id=t.id
                WHERE tm.user_id=%s AND tm.role='lead' AND tm.status='active'
                  AND t.status IN ('forming','applied')
                ORDER BY t.name""", (g.user["id"],))

    return render_template("student/project_detail.html", project=project,
                           today=date.today(), application=application,
                           independent=is_independent_student(),
                           my_teams=my_teams,
                           saved=bool(scalar(
                               "SELECT COUNT(*) FROM bookmarks WHERE user_id=%s "
                               "AND project_id=%s", (g.user["id"], project_id))))


# Where a submission currently sits, in words a student can act on.
WHO_HAS_IT = {
    "with_lecturer": "with your supervisor",
    "with_university": "with the university",
    "with_company": "with the company",
    "awaiting_team": "waiting on your teammates",
}


def in_review(assignment_id):
    """The version the chain is holding, if any. None means free to submit."""
    return query(
        """SELECT id, version, stage, submitted_at, updated_at
             FROM submissions
            WHERE assignment_id=%s
              AND stage IN ('with_lecturer','with_university','with_company',
                            'awaiting_team')
            ORDER BY version DESC LIMIT 1""", (assignment_id,), one=True)


@student_bp.route("/work/<int:assignment_id>", methods=["GET", "POST"])
@role_required("student")
def work(assignment_id):
    row = query(
        """SELECT a.*, p.title, p.description, p.deliverables, p.deadline,
                  c.name AS company_name, lec.fullname AS lecturer_name
             FROM assignments a
             JOIN projects p ON p.id=a.project_id
             JOIN companies c ON c.id=p.company_id
             LEFT JOIN users lec ON lec.id=a.lecturer_id
            WHERE a.id=%s AND a.student_id=%s""",
        (assignment_id, g.user["id"]), one=True)
    if not row:
        abort(404)

    if request.method == "POST":
        if row["status"] == "pending":
            flash("The company has not approved this placement yet.", "error")
            return redirect(url_for("student.work", assignment_id=assignment_id))
        if row["status"] == "cancelled":
            flash("This placement was declined by the company.", "error")
            return redirect(url_for("student.dashboard"))

        repo_url = request.form.get("repo_url", "").strip()
        notes = request.form.get("notes", "").strip()
        uploads = [f for f in request.files.getlist("files") if f and f.filename]

        errors = []
        if repo_url and not repo_url.startswith(
                ("https://github.com/", "https://gitlab.com/")):
            errors.append("A repository link must point at GitHub or GitLab.")
        if not repo_url and not uploads:
            errors.append("Attach your project files, or paste a repository link.")

        total = 0
        for item in uploads:
            try:
                storage.check_name(item.filename)
            except storage.UploadError as exc:
                errors.append(str(exc))
            item.stream.seek(0, 2)
            total += item.stream.tell()
            item.stream.seek(0)

        if total > storage.MAX_SUBMISSION_BYTES:
            errors.append(
                f"Those files come to {storage.human_size(total)}. One submission "
                f"can carry up to {storage.human_size(storage.MAX_SUBMISSION_BYTES)}.")

        # Nothing to send while the chain still holds the last version —
        # two live versions would leave reviewers arguing over which is current.
        held = in_review(assignment_id)
        if held:
            errors.append(
                f"Version {held['version']} is {WHO_HAS_IT[held['stage']]} at the "
                f"moment. You can send a new version once they respond.")

        if errors:
            for message in errors:
                flash(message, "error")
            return redirect(url_for("student.work", assignment_id=assignment_id))

        # Submitting against a named deliverable, if the supervisor set any.
        deliverable_id = None
        raw_deliverable = request.form.get("deliverable_id", "")
        if raw_deliverable.isdigit():
            allowed = scalar(
                """SELECT COUNT(*) FROM deliverables
                    WHERE id=%s AND project_id=%s AND status='published'""",
                (int(raw_deliverable), row["project_id"]))
            if not allowed:
                flash("That deliverable is not open for submissions.", "error")
                return redirect(url_for("student.work", assignment_id=assignment_id))
            deliverable_id = int(raw_deliverable)

        # On a team, the work waits for every other member to confirm.
        teammates = [uid for uid in team_member_ids(row["team_id"])
                     if uid != g.user["id"]]
        stage = "awaiting_team" if teammates else first_stage(row["lecturer_id"])
        saved, submission_id, version = [], None, None
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COALESCE(MAX(version),0)+1 AS v FROM submissions
                        WHERE assignment_id=%s""", (assignment_id,))
                version = cur.fetchone()["v"]

                cur.execute(
                    """INSERT INTO submissions
                       (assignment_id, version, repo_url, notes, stage,
                        team_id, created_by, deliverable_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (assignment_id, version, repo_url or None, notes or None, stage,
                     row["team_id"], g.user["id"], deliverable_id))
                submission_id = cur.fetchone()["id"]

                for uid in teammates:
                    cur.execute(
                        """INSERT INTO submission_confirmations
                           (submission_id, user_id) VALUES (%s,%s)""",
                        (submission_id, uid))

                for item in uploads:
                    meta = storage.save_submission_file(item, assignment_id, version)
                    saved.append(meta)
                    cur.execute(
                        """INSERT INTO submission_files
                           (submission_id, uploaded_by, original_name, stored_name,
                            relative_path, size_bytes, mime_type, sha256)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (submission_id, g.user["id"], meta["original_name"],
                         meta["stored_name"], meta["relative_path"],
                         meta["size_bytes"], meta["mime_type"], meta["sha256"]))

                cur.execute("UPDATE assignments SET status='submitted' WHERE id=%s",
                            (assignment_id,))
            conn.commit()
        except storage.UploadError as exc:
            conn.rollback()
            storage.delete_submission_files(saved)
            flash(str(exc), "error")
            return redirect(url_for("student.work", assignment_id=assignment_id))
        except Exception:
            conn.rollback()
            # The rows are gone; do not leave orphan files behind.
            storage.delete_submission_files(saved)
            raise

        count = len(saved)
        carried = (f"{count} file{'s' if count != 1 else ''}" if count
                   else "a repository link")

        if stage == "awaiting_team":
            for uid in teammates:
                notify(uid,
                       f"{g.user['fullname']} prepared version {version} of the team's "
                       f"work on \"{row['title']}\". It needs your confirmation.",
                       url_for("student.work", assignment_id=assignment_id))
            flash(f"Waiting on {len(teammates)} teammate"
                  f"{'' if len(teammates) == 1 else 's'} to confirm before it goes out.",
                  "success")
        elif stage == "with_lecturer":
            notify(row["lecturer_id"],
                   f"{g.user['fullname']} submitted work on \"{row['title']}\" "
                   f"(version {version}, {carried}).",
                   url_for("lecturer.inbox"))
            flash(f"Sent to your supervisor with {carried}.", "success")
        else:
            # Independent student: no lecturer, so it goes to the company.
            company_user = query(
                """SELECT co.user_id FROM assignments a
                     JOIN projects p ON p.id = a.project_id
                     JOIN companies co ON co.id = p.company_id
                    WHERE a.id=%s""", (assignment_id,), one=True)
            notify(company_user and company_user["user_id"],
                   f"{g.user['fullname']} submitted work on \"{row['title']}\" "
                   f"(version {version}, {carried}).",
                   url_for("company.inbox"))
            flash(f"Sent to {row['company_name']} with {carried}.", "success")

        return redirect(url_for("student.work", assignment_id=assignment_id))

    submissions = query(
        "SELECT * FROM submissions WHERE assignment_id=%s ORDER BY version DESC",
        (assignment_id,))
    held = in_review(assignment_id)
    for sub in submissions:
        sub["files"] = submission_files(sub["id"])
        sub["confirmations"] = query(
            """SELECT sc.*, u.fullname FROM submission_confirmations sc
                 JOIN users u ON u.id = sc.user_id
                WHERE sc.submission_id=%s ORDER BY u.fullname""", (sub["id"],))
        sub["my_confirmation"] = next(
            (c for c in sub["confirmations"] if c["user_id"] == g.user["id"]), None)
    timeline = history(submissions[0]["id"]) if submissions else []

    return render_template(
        "student/work.html", row=row,
        milestones=query(
            """SELECT m.*, su.fullname AS signer_name
                 FROM milestones m
                 LEFT JOIN users su ON su.id = m.signed_off_by
                WHERE m.assignment_id=%s ORDER BY m.phase""", (assignment_id,)),
        submissions=submissions, timeline=timeline, today=date.today(),
        stage_label=STAGE_LABEL, human_size=storage.human_size,
        max_file=storage.human_size(storage.MAX_FILE_BYTES),
        max_total=storage.human_size(storage.MAX_SUBMISSION_BYTES),
        held=held, who_has_it=WHO_HAS_IT,
        deliverables=published_for(row["project_id"]),
        teammates=query(
            """SELECT u.fullname FROM team_members tm JOIN users u ON u.id=tm.user_id
                WHERE tm.team_id=%s AND tm.status='active' AND tm.user_id<>%s""",
            (row["team_id"], g.user["id"])) if row["team_id"] else [])


@student_bp.route("/profile", methods=["GET", "POST"])
@role_required("student")
def profile():
    uid = g.user["id"]

    if request.method == "POST":
        github = request.form.get("github_url", "").strip()
        if github and not github.startswith("https://github.com/"):
            flash("Enter a full GitHub profile link starting with https://github.com/", "error")
        else:
            execute(
                """UPDATE student_profiles
                      SET github_url=%s, bio=%s, phone=%s, department=%s,
                          level=%s, available=%s
                    WHERE user_id=%s""",
                (github or None, request.form.get("bio", "").strip() or None,
                 request.form.get("phone", "").strip() or None,
                 request.form.get("department", "").strip() or None,
                 request.form.get("level", "").strip() or None,
                 "available" in request.form, uid))
            flash("Profile updated.", "success")
        return redirect(url_for("student.profile"))

    profile_row = query(
        """SELECT sp.*, f.name AS field_name, u.name AS university_name
             FROM student_profiles sp
             LEFT JOIN fields f ON f.id=sp.field_id
             LEFT JOIN universities u ON u.id=sp.university_id
            WHERE sp.user_id=%s""", (uid,), one=True) or {}

    work_history = query(
        """SELECT p.title, p.deadline, c.name AS company_name, a.status,
                  (SELECT repo_url FROM submissions s WHERE s.assignment_id=a.id
                    ORDER BY version DESC LIMIT 1) AS repo_url,
                  (SELECT string_agg(sk.name, ', ' ORDER BY sk.name)
                     FROM project_skills ps JOIN skills sk ON sk.id=ps.skill_id
                    WHERE ps.project_id=p.id) AS skill_list
             FROM assignments a
             JOIN projects p ON p.id=a.project_id
             JOIN companies c ON c.id=p.company_id
            WHERE a.student_id=%s ORDER BY a.assigned_at DESC""", (uid,))

    certificates = query(
        """SELECT ce.certificate_number, ce.issued_at, p.title, c.name AS company_name
             FROM certificates ce JOIN projects p ON p.id=ce.project_id
             JOIN companies c ON c.id=p.company_id
            WHERE ce.student_id=%s ORDER BY ce.issued_at DESC""", (uid,))

    return render_template(
        "student/profile.html", profile=profile_row,
        work_history=work_history, certificates=certificates,
        all_skills=query("SELECT id, name FROM skills ORDER BY name"),
        my_skills={r["skill_id"] for r in query(
            "SELECT skill_id FROM student_skills WHERE user_id=%s", (uid,))})


# ------------------------------------------------------- direct applications
#
# Students who joined on the main page have no lecturer to place them, so they
# ask the company themselves. A lecturer-placed student never sees these
# routes — their placements still come through their supervisor.

@student_bp.route("/projects/<int:project_id>/apply", methods=["POST"])
@role_required("student")
@subscription_required
def apply(project_id):
    if not is_independent_student():
        flash("Your lecturer places you on projects. Speak to them about this brief.",
              "error")
        return redirect(url_for("student.project_detail", project_id=project_id))

    project = query(
        """SELECT p.id, p.title, p.max_students, c.user_id AS company_user_id,
                  c.name AS company_name
             FROM projects p JOIN companies c ON c.id = p.company_id
            WHERE p.id=%s AND p.status='open' AND p.deadline >= CURRENT_DATE""",
        (project_id,), one=True)
    if not project:
        flash("That brief is no longer open.", "error")
        return redirect(url_for("student.browse"))

    message = request.form.get("message", "").strip()
    if len(message) < 30:
        flash("Tell the company why you fit — at least 30 characters.", "error")
        return redirect(url_for("student.project_detail", project_id=project_id))

    # Applying on behalf of a team, if the student leads one.
    team_id = None
    raw_team = request.form.get("team_id", "")
    if raw_team.isdigit():
        team = query(
            """SELECT t.* FROM teams t JOIN team_members tm ON tm.team_id=t.id
                WHERE t.id=%s AND tm.user_id=%s AND tm.role='lead'
                  AND tm.status='active'""",
            (int(raw_team), g.user["id"]), one=True)
        if not team:
            flash("You do not lead that team.", "error")
            return redirect(url_for("student.project_detail", project_id=project_id))
        if team["status"] not in ("forming", "applied"):
            flash("That team is already working on a brief.", "error")
            return redirect(url_for("student.project_detail", project_id=project_id))

        size = scalar("SELECT COUNT(*) FROM team_members WHERE team_id=%s "
                      "AND status='active'", (team["id"],))
        if size > project["max_students"]:
            flash(f"Your team has {size} members but this brief has only "
                  f"{project['max_students']} place(s).", "error")
            return redirect(url_for("student.project_detail", project_id=project_id))
        team_id = team["id"]

    existing = query(
        "SELECT id, status FROM project_applications WHERE project_id=%s AND student_id=%s",
        (project_id, g.user["id"]), one=True)
    if existing and existing["status"] in ("pending", "accepted"):
        flash("You have already applied for this brief.", "error")
        return redirect(url_for("student.project_detail", project_id=project_id))

    if existing:
        execute(
            """UPDATE project_applications
                  SET message=%s, status='pending', created_at=NOW(),
                      decided_at=NULL, decided_by=NULL, team_id=%s
                WHERE id=%s""", (message, team_id, existing["id"]))
    else:
        execute(
            """INSERT INTO project_applications
               (project_id, student_id, message, team_id)
               VALUES (%s,%s,%s,%s)""", (project_id, g.user["id"], message, team_id))

    if team_id:
        execute("UPDATE teams SET status='applied', project_id=%s WHERE id=%s",
                (project_id, team_id))

    notify(project["company_user_id"],
           f"{g.user['fullname']} applied for \"{project['title']}\".",
           url_for("company.applications"))
    flash(f"Sent to {project['company_name']}. You will be told when they decide.",
          "success")
    return redirect(url_for("student.applications"))


@student_bp.route("/applications")
@role_required("student")
def applications():
    rows = query(
        """SELECT pa.id, pa.status, pa.message AS cover_letter,
                  pa.created_at AS applied_at, pa.decided_at,
                  p.id AS project_id, p.title, p.deadline,
                  c.name AS client_name,
                  (SELECT a.id FROM assignments a
                    WHERE a.project_id=pa.project_id AND a.student_id=pa.student_id
                    LIMIT 1) AS assignment_id
             FROM project_applications pa
             JOIN projects p ON p.id = pa.project_id
             JOIN companies c ON c.id = p.company_id
            WHERE pa.student_id=%s
            ORDER BY pa.created_at DESC""", (g.user["id"],))
    return render_template("student/applications.html", applications=rows,
                           independent=is_independent_student())


@student_bp.route("/applications/<int:application_id>/withdraw", methods=["POST"])
@role_required("student")
def withdraw(application_id):
    row = query(
        "SELECT * FROM project_applications WHERE id=%s AND student_id=%s",
        (application_id, g.user["id"]), one=True)
    if not row:
        abort(404)
    if row["status"] != "pending":
        flash("That application has already been decided.", "error")
        return redirect(url_for("student.applications"))

    execute("UPDATE project_applications SET status='withdrawn', decided_at=NOW() "
            "WHERE id=%s", (application_id,))
    flash("Application withdrawn.", "success")
    return redirect(url_for("student.applications"))


# ------------------------------------------------------------ project record

@student_bp.route("/placements/<int:assignment_id>/record")
@role_required("student")
def record(assignment_id):
    """Everything kept about one placement: dates, versions, files, decisions.

    This is the page to open when someone asks what was delivered and when.
    """
    row = query(
        """SELECT a.*, p.title, p.description, p.deliverables, p.difficulty,
                  p.deadline, p.created_at AS project_created_at,
                  p.published_at, p.completed_at AS project_completed_at,
                  p.status AS project_status,
                  f.name AS field_name,
                  c.name AS company_name, c.website AS company_website,
                  lec.fullname AS lecturer_name,
                  uni.name AS university_name
             FROM assignments a
             JOIN projects p ON p.id = a.project_id
             JOIN fields f ON f.id = p.field_id
             JOIN companies c ON c.id = p.company_id
             LEFT JOIN users lec ON lec.id = a.lecturer_id
             LEFT JOIN lecturer_profiles lp ON lp.user_id = a.lecturer_id
             LEFT JOIN universities uni ON uni.id = lp.university_id
            WHERE a.id=%s AND a.student_id=%s""",
        (assignment_id, g.user["id"]), one=True)
    if not row:
        abort(404)

    submissions = query(
        "SELECT * FROM submissions WHERE assignment_id=%s ORDER BY version DESC",
        (assignment_id,))
    held = in_review(assignment_id)
    for sub in submissions:
        sub["files"] = submission_files(sub["id"])
        sub["trail"] = history(sub["id"])

    certificate = query(
        """SELECT certificate_number, issued_at FROM certificates
            WHERE student_id=%s AND project_id=%s""",
        (g.user["id"], row["project_id"]), one=True)

    everything = files_for_assignment(assignment_id)

    return render_template(
        "student/record.html", row=row, submissions=submissions,
        milestones=query(
            """SELECT m.*, su.fullname AS signer_name
                 FROM milestones m
                 LEFT JOIN users su ON su.id = m.signed_off_by
                WHERE m.assignment_id=%s ORDER BY m.phase""", (assignment_id,)),
        certificate=certificate, all_files=everything,
        total_bytes=sum(f["size_bytes"] for f in everything),
        human_size=storage.human_size, stage_label=STAGE_LABEL, today=date.today())


# ------------------------------------------------------- bookmarks and skills

@student_bp.route("/projects/<int:project_id>/bookmark", methods=["POST"])
@role_required("student")
def bookmark(project_id):
    """Save or unsave a brief. Harmless either way, so it just toggles."""
    if not scalar("SELECT COUNT(*) FROM projects WHERE id=%s AND status='open'",
                  (project_id,)):
        abort(404)

    already = scalar("SELECT COUNT(*) FROM bookmarks WHERE user_id=%s AND project_id=%s",
                     (g.user["id"], project_id))
    if already:
        execute("DELETE FROM bookmarks WHERE user_id=%s AND project_id=%s",
                (g.user["id"], project_id))
    else:
        execute("INSERT INTO bookmarks (user_id, project_id) VALUES (%s,%s) "
                "ON CONFLICT DO NOTHING", (g.user["id"], project_id))

    flash("Removed from your saved briefs." if already else "Saved.", "success")
    return redirect(request.referrer or url_for("student.browse"))


@student_bp.route("/bookmarks")
@role_required("student")
def bookmarks():
    projects = query(
        """SELECT p.*, c.name AS company_name, f.name AS field_name,
                  f.image_url AS field_image, c.logo_url AS company_logo,
                  b.created_at AS saved_at,
                  (SELECT string_agg(s.name, ', ') FROM project_skills ps
                     JOIN skills s ON s.id = ps.skill_id
                    WHERE ps.project_id = p.id) AS skill_list
             FROM bookmarks b
             JOIN projects p ON p.id = b.project_id
             JOIN companies c ON c.id = p.company_id
             JOIN fields f ON f.id = p.field_id
            WHERE b.user_id=%s
            ORDER BY b.created_at DESC""", (g.user["id"],))
    matching.annotate(projects, g.user["id"])
    return render_template("student/bookmarks.html", projects=projects,
                           today=date.today())


@student_bp.route("/skills", methods=["POST"])
@role_required("student")
def save_skills():
    """What the student can do. Drives the match score on the feed."""
    chosen = {int(v) for v in request.form.getlist("skills") if v.isdigit()}
    valid = {r["id"] for r in query("SELECT id FROM skills")}
    chosen &= valid

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM student_skills WHERE user_id=%s", (g.user["id"],))
            for skill_id in chosen:
                cur.execute(
                    "INSERT INTO student_skills (user_id, skill_id) VALUES (%s,%s)",
                    (g.user["id"], skill_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    flash(f"{len(chosen)} skill{'' if len(chosen) == 1 else 's'} saved. "
          "Briefs are now scored against them.", "success")
    return redirect(url_for("student.profile"))


# --------------------------------------------------- confirming team submissions

@student_bp.route("/submissions/<int:submission_id>/<decision>", methods=["POST"])
@role_required("student")
def confirm(submission_id, decision):
    """A teammate signs off on work before it leaves the team.

    Everyone active on the team has to confirm. One rejection sends the whole
    thing back so it can be fixed, rather than letting a majority overrule.
    """
    if decision not in ("confirm", "reject"):
        abort(400)

    sub = query(
        """SELECT s.*, a.team_id, a.lecturer_id, a.id AS assignment_id,
                  p.title, c.user_id AS company_user_id
             FROM submissions s
             JOIN assignments a ON a.id = s.assignment_id
             JOIN projects p ON p.id = a.project_id
             JOIN companies c ON c.id = p.company_id
            WHERE s.id=%s""", (submission_id,), one=True)
    if not sub:
        abort(404)

    mine = query(
        "SELECT * FROM submission_confirmations WHERE submission_id=%s AND user_id=%s",
        (submission_id, g.user["id"]), one=True)
    if not mine:
        abort(403)
    if sub["stage"] != "awaiting_team":
        flash("This submission has already left the team.", "error")
        return redirect(url_for("student.work", assignment_id=sub["assignment_id"]))
    if mine["decision"] != "pending":
        flash("You have already given your answer on this one.", "error")
        return redirect(url_for("student.work", assignment_id=sub["assignment_id"]))

    comment = request.form.get("comment", "").strip()
    execute(
        """UPDATE submission_confirmations
              SET decision=%s, comment=%s, decided_at=NOW()
            WHERE id=%s""",
        ("confirmed" if decision == "confirm" else "rejected",
         comment or None, mine["id"]))

    if decision == "reject":
        execute("UPDATE submissions SET stage='changes_requested', updated_at=NOW() "
                "WHERE id=%s", (submission_id,))
        for uid in team_member_ids(sub["team_id"]):
            if uid != g.user["id"]:
                notify(uid,
                       f"{g.user['fullname']} asked for changes on the team's "
                       f"submission for \"{sub['title']}\".",
                       url_for("student.work", assignment_id=sub["assignment_id"]))
        flash("Sent back to the team for changes.", "success")
        return redirect(url_for("student.work", assignment_id=sub["assignment_id"]))

    still_waiting = scalar(
        "SELECT COUNT(*) FROM submission_confirmations "
        "WHERE submission_id=%s AND decision='pending'", (submission_id,))

    if still_waiting:
        flash(f"Confirmed. Waiting on {still_waiting} more "
              f"teammate{'' if still_waiting == 1 else 's'}.", "success")
        return redirect(url_for("student.work", assignment_id=sub["assignment_id"]))

    # Everyone has confirmed — the work leaves the team.
    stage = first_stage(sub["lecturer_id"])
    execute("UPDATE submissions SET stage=%s, updated_at=NOW() WHERE id=%s",
            (stage, submission_id))
    execute("UPDATE assignments SET status='submitted' WHERE team_id=%s",
            (sub["team_id"],))

    recipient = sub["lecturer_id"] if stage == "with_lecturer" else sub["company_user_id"]
    target = url_for("lecturer.inbox") if stage == "with_lecturer" else url_for("company.inbox")
    notify(recipient,
           f"A team submitted work on \"{sub['title']}\" (version {sub['version']}).",
           target)

    for uid in team_member_ids(sub["team_id"]):
        notify(uid, f"Your team's submission for \"{sub['title']}\" has gone out "
                    f"for review.",
               url_for("student.work", assignment_id=sub["assignment_id"]))

    flash("Everyone has confirmed. The submission is on its way.", "success")
    return redirect(url_for("student.work", assignment_id=sub["assignment_id"]))


def team_member_ids(team_id):
    if not team_id:
        return []
    return [r["user_id"] for r in query(
        "SELECT user_id FROM team_members WHERE team_id=%s AND status='active'",
        (team_id,))]
