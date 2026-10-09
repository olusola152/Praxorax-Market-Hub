from datetime import date, timedelta

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

from auth_utils import log_action, role_required
from db import execute, query, scalar
from workflow import notify

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

SUB_STATUSES = ("pending", "trial", "active", "expired", "suspended")
DEFAULT_TERM_DAYS = 365


@admin_bp.route("/dashboard")
@role_required("admin")
def dashboard():
    """The operations deck.

    An administrator is not reading records here, they are watching a system.
    So the first thing on the page is the review chain — how much work is
    sitting with whom — because that is what tells you whether the platform is
    moving or stuck.
    """
    stats = {
        "students": scalar("SELECT COUNT(*) FROM users WHERE role='student'"),
        "lecturers": scalar("SELECT COUNT(*) FROM users WHERE role='lecturer'"),
        "universities": scalar("SELECT COUNT(*) FROM universities"),
        "companies": scalar("SELECT COUNT(*) FROM companies"),
        "blocked": scalar("SELECT COUNT(*) FROM users WHERE status='blocked'"),
        "projects": scalar("SELECT COUNT(*) FROM projects"),
        "placements": scalar("SELECT COUNT(*) FROM assignments"),
        "completed": scalar("SELECT COUNT(*) FROM assignments WHERE status='completed'"),
        "independent": scalar(
            """SELECT COUNT(*) FROM student_profiles WHERE university_id IS NULL"""),
        "pending_subs": scalar(
            """SELECT (SELECT COUNT(*) FROM universities WHERE subscription_status='pending')
                    + (SELECT COUNT(*) FROM companies WHERE subscription_status='pending')"""),
        "pending_kyc": scalar(
            """SELECT COUNT(*) FROM companies
                WHERE verification_status='pending' AND kyc_document_url IS NOT NULL"""),
        "open_requests": scalar(
            "SELECT COUNT(*) FROM project_requests WHERE status='pending'"),
        "open_applications": scalar(
            "SELECT COUNT(*) FROM project_applications WHERE status='pending'"),
    }

    # Where submitted work is sitting right now. This is the health check.
    chain = {row["stage"]: row["n"] for row in query(
        """SELECT stage, COUNT(*) AS n FROM submissions
            WHERE stage IN ('awaiting_team','with_lecturer','with_university',
                            'with_company','revision')
            GROUP BY stage""")}
    stages = [
        ("awaiting_team", "Waiting on teammates"),
        ("with_lecturer", "With supervisors"),
        ("with_university", "With universities"),
        ("with_company", "With companies"),
        ("revision", "Back for corrections"),
    ]
    board = [{"key": k, "label": label, "n": chain.get(k, 0)} for k, label in stages]
    busiest = max((b["n"] for b in board), default=0) or 1
    for item in board:
        item["share"] = round(item["n"] / busiest * 100)

    # Anything older than a week in one pair of hands is a held-up student.
    stalled = query(
        """SELECT s.id, s.version, s.stage, s.updated_at, p.title,
                  stu.fullname AS student_name,
                  EXTRACT(DAY FROM NOW() - s.updated_at)::int AS days_waiting
             FROM submissions s
             JOIN assignments a ON a.id = s.assignment_id
             JOIN projects p ON p.id = a.project_id
             JOIN users stu ON stu.id = a.student_id
            WHERE s.stage IN ('with_lecturer','with_university','with_company')
              AND s.updated_at < NOW() - INTERVAL '7 days'
            ORDER BY s.updated_at LIMIT 8""")

    # Twelve weeks of signups, for the shape rather than the exact numbers.
    weeks = query(
        """SELECT to_char(week, 'DD Mon') AS label, COALESCE(n, 0) AS n
             FROM generate_series(
                    date_trunc('week', NOW()) - INTERVAL '11 weeks',
                    date_trunc('week', NOW()), INTERVAL '1 week') AS week
             LEFT JOIN (
                  SELECT date_trunc('week', created_at) AS w, COUNT(*) AS n
                    FROM users GROUP BY 1) counts ON counts.w = week
            ORDER BY week""")
    peak = max([w["n"] for w in weeks] or [0]) or 1
    points = " ".join(
        f"{i * (600 / max(len(weeks) - 1, 1)):.1f},{90 - (w['n'] / peak * 76):.1f}"
        for i, w in enumerate(weeks))

    recent = query(
        """SELECT u.fullname, u.email, u.role, u.status, u.created_at
             FROM users u ORDER BY u.created_at DESC LIMIT 8""")
    activity = query(
        """SELECT a.action, a.target_type, a.target_id, a.detail, a.created_at,
                  u.fullname AS actor
             FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id
            ORDER BY a.created_at DESC LIMIT 10""")

    return render_template("admin/dashboard.html", stats=stats, recent=recent,
                           activity=activity, board=board, stalled=stalled,
                           weeks=weeks, spark_points=points, peak=peak,
                           in_flight=sum(b["n"] for b in board))


@admin_bp.route("/users")
@role_required("admin")
def users():
    role = request.args.get("role", "")
    search = request.args.get("q", "").strip()

    sql = """SELECT u.id, u.fullname, u.email, u.role, u.status, u.created_at,
                    u.last_login_at, u.blocked_reason,
                    COALESCE(uni.name, luni.name, c.name) AS org
               FROM users u
               LEFT JOIN student_profiles sp ON sp.user_id = u.id
               LEFT JOIN universities uni ON uni.id = sp.university_id
               LEFT JOIN lecturer_profiles lp ON lp.user_id = u.id
               LEFT JOIN universities luni ON luni.id = lp.university_id
               LEFT JOIN companies c ON c.user_id = u.id
              WHERE 1=1"""
    params = []
    if role in ("student", "lecturer", "university", "company", "admin"):
        sql += " AND u.role = %s"
        params.append(role)
    if search:
        sql += " AND (u.fullname ILIKE %s OR u.email ILIKE %s)"
        params += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY u.created_at DESC LIMIT 200"

    return render_template("admin/users.html", users=query(sql, tuple(params)),
                           role=role, search=search)


@admin_bp.route("/users/<int:user_id>/block", methods=["POST"])
@role_required("admin")
def block_user(user_id):
    if user_id == g.user["id"]:
        flash("You cannot block your own account.", "error")
        return redirect(url_for("admin.users"))

    reason = request.form.get("reason", "").strip() or None
    changed = execute(
        """UPDATE users SET status='blocked', blocked_reason=%s
            WHERE id=%s AND role <> 'admin' RETURNING id""",
        (reason, user_id), returning=True)

    if changed:
        log_action("block_user", "user", user_id, reason)
        flash("Account blocked. They are signed out on their next request.", "success")
    else:
        flash("That account could not be blocked.", "error")
    return redirect(request.referrer or url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/unblock", methods=["POST"])
@role_required("admin")
def unblock_user(user_id):
    changed = execute(
        """UPDATE users SET status='active', blocked_reason=NULL
            WHERE id=%s RETURNING id""", (user_id,), returning=True)
    if changed:
        log_action("unblock_user", "user", user_id)
        flash("Account unblocked.", "success")
    return redirect(request.referrer or url_for("admin.users"))


@admin_bp.route("/subscriptions")
@role_required("admin")
def subscriptions():
    universities = query(
        """SELECT u.*, adm.fullname AS admin_name, adm.email AS admin_email,
                  (SELECT COUNT(*) FROM lecturer_profiles lp WHERE lp.university_id = u.id)
                    AS lecturers,
                  (SELECT COUNT(*) FROM student_profiles sp WHERE sp.university_id = u.id)
                    AS students
             FROM universities u LEFT JOIN users adm ON adm.id = u.admin_user_id
            ORDER BY u.created_at DESC""")
    companies = query(
        """SELECT c.*, u.fullname AS admin_name, u.email AS admin_email,
                  (SELECT COUNT(*) FROM projects p WHERE p.company_id = c.id) AS projects
             FROM companies c JOIN users u ON u.id = c.user_id
            ORDER BY c.created_at DESC""")
    return render_template("admin/subscriptions.html", universities=universities,
                           companies=companies, today=date.today())


@admin_bp.route("/subscriptions/<kind>/<int:record_id>", methods=["POST"])
@role_required("admin")
def set_subscription(kind, record_id):
    if kind not in ("university", "company"):
        abort(404)
    status = request.form.get("status", "")
    if status not in SUB_STATUSES:
        abort(400)

    months = request.form.get("months", "")
    until = None
    if status == "active":
        try:
            days = int(months) * 30 if months else DEFAULT_TERM_DAYS
        except ValueError:
            days = DEFAULT_TERM_DAYS
        until = date.today() + timedelta(days=days)

    table = "universities" if kind == "university" else "companies"
    changed = execute(
        f"""UPDATE {table} SET subscription_status=%s, subscribed_until=%s
             WHERE id=%s RETURNING id""", (status, until, record_id), returning=True)

    if changed:
        log_action("set_subscription", kind, record_id, status)
        flash(f"Subscription set to {status}.", "success")
    return redirect(url_for("admin.subscriptions"))


@admin_bp.route("/activity")
@role_required("admin")
def activity():
    rows = query(
        """SELECT a.*, u.fullname AS actor, u.role AS actor_role
             FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id
            ORDER BY a.created_at DESC LIMIT 300""")
    return render_template("admin/activity.html", rows=rows)

@admin_bp.route("/universities")
@role_required("admin")
def universities():
    rows = query(
        """SELECT u.*, adm.fullname AS admin_name, adm.email AS admin_email,
                  adm.status AS admin_status, adm.id AS admin_id,
                  (SELECT COUNT(*) FROM lecturer_profiles lp WHERE lp.university_id = u.id)
                    AS lecturers,
                  (SELECT COUNT(*) FROM student_profiles sp WHERE sp.university_id = u.id)
                    AS students,
                  (SELECT COUNT(*) FROM passcodes p
                    WHERE p.university_id = u.id AND p.used_at IS NULL
                      AND p.expires_at > NOW()) AS open_codes,
                  (SELECT COUNT(*) FROM assignments a
                     JOIN lecturer_profiles lp2 ON lp2.user_id = a.lecturer_id
                    WHERE lp2.university_id = u.id) AS placements
             FROM universities u
             LEFT JOIN users adm ON adm.id = u.admin_user_id
            ORDER BY u.created_at DESC""")
    return render_template("admin/universities.html", universities=rows,
                           today=date.today())


@admin_bp.route("/companies")
@role_required("admin")
def companies():
    rows = query(
        """SELECT c.*, u.fullname AS admin_name, u.email AS admin_email,
                  u.status AS admin_status, u.id AS admin_id,
                  (SELECT COUNT(*) FROM projects p WHERE p.company_id = c.id) AS projects,
                  (SELECT COUNT(*) FROM projects p
                    WHERE p.company_id = c.id AND p.status = 'open') AS open_projects,
                  (SELECT COUNT(*) FROM assignments a
                     JOIN projects p2 ON p2.id = a.project_id
                    WHERE p2.company_id = c.id) AS placements
             FROM companies c JOIN users u ON u.id = c.user_id
            ORDER BY c.created_at DESC""")
    return render_template("admin/companies.html", companies=rows, today=date.today())


@admin_bp.route("/projects")
@role_required("admin")
def projects():
    status = request.args.get("status", "")
    search = request.args.get("q", "").strip()

    sql = """SELECT p.id, p.title, p.status, p.deadline,
                    p.max_students, p.created_at, f.name AS field_name,
                    c.name AS company_name, c.subscription_status,
                    (SELECT COUNT(*) FROM submissions s
                       JOIN assignments a2 ON a2.id = s.assignment_id
                      WHERE a2.project_id = p.id) AS submissions,
                    (SELECT COUNT(*) FROM assignments asg
                      WHERE asg.project_id = p.id) AS students_on
               FROM projects p
               JOIN fields f ON f.id = p.field_id
               JOIN companies c ON c.id = p.company_id
              WHERE 1=1"""
    params = []
    if status in ("draft", "open", "engaged", "completed", "cancelled"):
        sql += " AND p.status = %s"
        params.append(status)
    if search:
        sql += " AND (p.title ILIKE %s OR c.name ILIKE %s)"
        params += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY p.created_at DESC LIMIT 200"

    return render_template("admin/projects.html", projects=query(sql, tuple(params)),
                           status=status, search=search, today=date.today())


@admin_bp.route("/projects/<int:project_id>/cancel", methods=["POST"])
@role_required("admin")
def cancel_project(project_id):
    """Moderation: pull a brief that breaches the rules."""
    reason = request.form.get("reason", "").strip() or None
    changed = execute(
        """UPDATE projects SET status = 'cancelled'
            WHERE id = %s AND status IN ('draft','open') RETURNING id""",
        (project_id,), returning=True)

    if changed:
        log_action("cancel_project", "project", project_id, reason)
        flash("Project cancelled.", "success")
    else:
        flash("Only draft or open projects can be cancelled.", "error")
    return redirect(request.referrer or url_for("admin.projects"))


@admin_bp.route("/placements")
@role_required("admin")
def placements():
    rows = query(
        """SELECT asg.id, asg.status, asg.assigned_at,
                  stu.fullname AS student_name, lec.fullname AS lecturer_name,
                  uni.name AS university_name, c.name AS company_name,
                  p.title, p.deadline,
                  (SELECT COUNT(*) FROM milestones m
                    WHERE m.assignment_id = asg.id AND m.status = 'done') AS done,
                  (SELECT COUNT(*) FROM milestones m
                    WHERE m.assignment_id = asg.id) AS total,
                  (SELECT COUNT(*) FROM milestones m
                    WHERE m.assignment_id = asg.id AND m.status <> 'done'
                      AND m.due_date < CURRENT_DATE) AS overdue
             FROM assignments asg
             JOIN users stu ON stu.id = asg.student_id
             LEFT JOIN users lec ON lec.id = asg.lecturer_id
             LEFT JOIN lecturer_profiles lp ON lp.user_id = lec.id
             LEFT JOIN universities uni ON uni.id = lp.university_id
             JOIN projects p ON p.id = asg.project_id
             JOIN companies c ON c.id = p.company_id
            ORDER BY p.deadline LIMIT 300""")
    return render_template("admin/placements.html", placements=rows, today=date.today())


@admin_bp.route("/notifications")
@role_required("admin")
def notifications():
    rows = query(
        "SELECT * FROM notifications WHERE user_id=%s ORDER BY created_at DESC LIMIT 100",
        (g.user["id"],))
    execute("UPDATE notifications SET read_at=NOW() WHERE user_id=%s AND read_at IS NULL",
            (g.user["id"],))
    return render_template("shared/notifications.html", rows=rows)


# ------------------------------------------------------------------- KYC
#
# Companies start unverified. Until an administrator here says otherwise,
# they can draft briefs but not publish them to students.

@admin_bp.route("/kyc")
@role_required("admin")
def kyc():
    companies = query(
        """SELECT c.*, u.fullname AS contact_name, u.email AS contact_email,
                  d.fullname AS decided_by_name,
                  (SELECT COUNT(*) FROM projects p WHERE p.company_id=c.id)
                    AS project_count
             FROM companies c
             JOIN users u ON u.id = c.user_id
             LEFT JOIN users d ON d.id = c.kyc_decided_by
            ORDER BY (c.verification_status='pending') DESC,
                     c.kyc_submitted_at DESC NULLS LAST, c.name""")
    return render_template("admin/kyc.html", companies=companies)


@admin_bp.route("/kyc/<int:company_id>/<decision>", methods=["POST"])
@role_required("admin")
def decide_kyc(company_id, decision):
    if decision not in ("verify", "reject"):
        abort(400)

    company = query("SELECT * FROM companies WHERE id=%s", (company_id,), one=True)
    if not company:
        abort(404)

    notes = request.form.get("notes", "").strip()
    if decision == "reject" and len(notes) < 10:
        flash("Say why it was rejected — the company sees this and needs to know "
              "what to fix.", "error")
        return redirect(url_for("admin.kyc"))

    status = "verified" if decision == "verify" else "rejected"
    execute("""UPDATE companies
                  SET verification_status=%s, kyc_notes=%s,
                      kyc_decided_at=NOW(), kyc_decided_by=%s
                WHERE id=%s""", (status, notes or None, g.user["id"], company_id))

    if status == "verified":
        notify(company["user_id"],
               "Your company has been verified. You can publish briefs now.",
               url_for("company.projects"))
    else:
        notify(company["user_id"],
               f"Your verification was not approved: {notes}",
               url_for("company.verification"))

    log_action(f"kyc_{status}", "company", company_id, notes or None)
    flash(f"{company['name']} marked {status}.", "success")
    return redirect(url_for("admin.kyc"))


# ------------------------------------------------------- public students
#
# Students who joined on the main page, with no university behind them. They
# are a different population from institutional students — nobody supervises
# them, nobody vouches for them, and no subscription covers them — so they get
# their own view rather than being buried in the user list.

@admin_bp.route("/public-students")
@role_required("admin")
def public_students():
    search = (request.args.get("q") or "").strip()
    state = request.args.get("state", "")

    sql = """SELECT u.id, u.fullname, u.email, u.status, u.created_at,
                    sp.department, sp.level, sp.github_url, sp.headline,
                    sp.portfolio_public, sp.portfolio_token,
                    f.name AS field_name,
                    (SELECT COUNT(*) FROM project_applications pa
                      WHERE pa.student_id = u.id) AS applications,
                    (SELECT COUNT(*) FROM project_applications pa
                      WHERE pa.student_id = u.id AND pa.status='pending')
                      AS waiting,
                    (SELECT COUNT(*) FROM assignments a
                      WHERE a.student_id = u.id AND a.status <> 'cancelled')
                      AS placements,
                    (SELECT COUNT(*) FROM assignments a
                      WHERE a.student_id = u.id AND a.status = 'completed')
                      AS completed,
                    (SELECT COUNT(*) FROM student_skills ss
                      WHERE ss.user_id = u.id) AS skills,
                    (SELECT MAX(s.submitted_at) FROM submissions s
                       JOIN assignments a2 ON a2.id = s.assignment_id
                      WHERE a2.student_id = u.id) AS last_submission
               FROM users u
               JOIN student_profiles sp ON sp.user_id = u.id
               LEFT JOIN fields f ON f.id = sp.field_id
              WHERE u.role = 'student' AND sp.university_id IS NULL"""
    params = []

    if search:
        sql += " AND (u.fullname ILIKE %s OR u.email ILIKE %s)"
        params += [f"%{search}%", f"%{search}%"]

    # Three states worth separating: working, waiting on a company, idle.
    if state == "placed":
        sql += """ AND EXISTS (SELECT 1 FROM assignments a WHERE a.student_id=u.id
                                AND a.status NOT IN ('cancelled','completed'))"""
    elif state == "waiting":
        sql += """ AND EXISTS (SELECT 1 FROM project_applications pa
                                WHERE pa.student_id=u.id AND pa.status='pending')"""
    elif state == "idle":
        sql += """ AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.student_id=u.id
                                    AND a.status <> 'cancelled')
                   AND NOT EXISTS (SELECT 1 FROM project_applications pa
                                    WHERE pa.student_id=u.id AND pa.status='pending')"""

    sql += " ORDER BY u.created_at DESC"
    rows = query(sql, tuple(params))

    totals = {
        "all": scalar("""SELECT COUNT(*) FROM student_profiles
                          WHERE university_id IS NULL"""),
        "placed": scalar("""SELECT COUNT(DISTINCT a.student_id) FROM assignments a
                              JOIN student_profiles sp ON sp.user_id = a.student_id
                             WHERE sp.university_id IS NULL
                               AND a.status NOT IN ('cancelled','completed')"""),
        "waiting": scalar("""SELECT COUNT(DISTINCT pa.student_id)
                               FROM project_applications pa
                               JOIN student_profiles sp ON sp.user_id = pa.student_id
                              WHERE sp.university_id IS NULL AND pa.status='pending'"""),
        "completed": scalar("""SELECT COUNT(*) FROM assignments a
                                 JOIN student_profiles sp ON sp.user_id = a.student_id
                                WHERE sp.university_id IS NULL
                                  AND a.status = 'completed'"""),
    }
    totals["idle"] = max(totals["all"] - totals["placed"] - totals["waiting"], 0)

    return render_template("admin/public_students.html", rows=rows, totals=totals,
                           search=search, state=state, today=date.today())
