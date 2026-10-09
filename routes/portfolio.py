"""A student's portfolio — everything they have finished, in one place.

Three views of the same record:

  /student/portfolio            the student's own, private, with controls
  /p/<token>                    the public version, no login, shareable
  /student/portfolio/certificate/<ref>   a printable consolidated certificate

The per-project certificates already issued when a company signs off are left
alone. What is added here is the document covering the whole record, with its
own reference number that anyone can check at /verify.
"""
import json
import secrets
from datetime import date, datetime, timezone

from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, url_for)

from auth_utils import role_required
from db import execute, query, scalar

portfolio_bp = Blueprint("portfolio", __name__)

# Plain English for a student wondering where their work has got to.
STAGE_TEXT = {
    "awaiting_team": "waiting on your teammates to confirm",
    "changes_requested": "your team asked for changes",
    "with_lecturer": "with your supervisor",
    "with_university": "with the university",
    "with_company": "with the company",
    "revision": "corrections requested",
    "approved": "approved",
}


# --------------------------------------------------------------- gathering

def completed_work(student_id):
    """Every placement the company has signed off, newest first.

    Only approved work appears. A portfolio that listed half-finished projects
    would be worth nothing to the employer reading it.
    """
    rows = query(
        """SELECT a.id AS assignment_id, a.assigned_at, a.completed_at,
                  a.source, a.team_id,
                  p.id AS project_id, p.title, p.description, p.deliverables,
                  p.difficulty, p.deadline, p.created_at AS brief_posted,
                  f.name AS field_name, f.faculty, f.image_url AS field_image,
                  c.name AS company_name, c.website AS company_website,
                  c.logo_url AS company_logo,
                  lec.fullname AS lecturer_name,
                  uni.name AS university_name,
                  t.name AS team_name,
                  ce.certificate_number, ce.issued_at AS certificate_issued,
                  (SELECT COUNT(*) FROM submissions s
                    WHERE s.assignment_id = a.id) AS version_count,
                  (SELECT COUNT(*) FROM submission_files sf
                     JOIN submissions s2 ON s2.id = sf.submission_id
                    WHERE s2.assignment_id = a.id) AS file_count,
                  (SELECT MAX(s3.submitted_at) FROM submissions s3
                    WHERE s3.assignment_id = a.id) AS last_submitted_at,
                  (SELECT string_agg(sk.name, ', ' ORDER BY sk.name)
                     FROM project_skills ps JOIN skills sk ON sk.id = ps.skill_id
                    WHERE ps.project_id = p.id) AS skills
             FROM assignments a
             JOIN projects p ON p.id = a.project_id
             JOIN fields f ON f.id = p.field_id
             JOIN companies c ON c.id = p.company_id
             LEFT JOIN users lec ON lec.id = a.lecturer_id
             LEFT JOIN lecturer_profiles lp ON lp.user_id = a.lecturer_id
             LEFT JOIN universities uni ON uni.id = lp.university_id
             LEFT JOIN teams t ON t.id = a.team_id
             LEFT JOIN certificates ce
                    ON ce.project_id = p.id AND ce.student_id = a.student_id
            WHERE a.student_id = %s AND a.status = 'completed'
            ORDER BY a.completed_at DESC NULLS LAST, a.id DESC""",
        (student_id,))

    for row in rows:
        row["worked_as"] = row["team_name"] or "Individually"
        row["route"] = ("Applied directly" if row["source"] == "direct"
                        else "Placed by a lecturer")
        if row["assigned_at"] and row["completed_at"]:
            row["days_taken"] = (row["completed_at"].date()
                                 - row["assigned_at"].date()).days
        else:
            row["days_taken"] = None
    return rows


def summarise(rows):
    """The headline numbers above the list."""
    fields, companies, skills = set(), set(), set()
    for row in rows:
        fields.add(row["field_name"])
        companies.add(row["company_name"])
        if row["skills"]:
            skills.update(s.strip() for s in row["skills"].split(","))

    spans = [r["days_taken"] for r in rows if r["days_taken"] is not None]
    return {
        "projects": len(rows),
        "companies": len(companies),
        "fields": sorted(fields),
        "skills": sorted(skills),
        "certificates": sum(1 for r in rows if r["certificate_number"]),
        "files": sum(r["file_count"] or 0 for r in rows),
        "versions": sum(r["version_count"] or 0 for r in rows),
        "median_days": sorted(spans)[len(spans) // 2] if spans else None,
        "first": rows[-1]["completed_at"] if rows else None,
        "latest": rows[0]["completed_at"] if rows else None,
    }


def profile_of(student_id):
    return query(
        """SELECT sp.*, u.fullname, u.email, u.created_at AS joined_at,
                  f.name AS field_name, uni.name AS university_name
             FROM student_profiles sp
             JOIN users u ON u.id = sp.user_id
             LEFT JOIN fields f ON f.id = sp.field_id
             LEFT JOIN universities uni ON uni.id = sp.university_id
            WHERE sp.user_id = %s""", (student_id,), one=True)


# ------------------------------------------------------- the student's own

@portfolio_bp.route("/student/portfolio")
@role_required("student")
def mine():
    rows = completed_work(g.user["id"])

    # When there is nothing to certify, show what is still in flight instead of
    # leaving the student to wonder why.
    pending = []
    if not rows:
        pending = query(
            """SELECT a.id, a.status, p.title, c.name AS company_name,
                      (SELECT s.stage FROM submissions s
                        WHERE s.assignment_id = a.id
                        ORDER BY s.version DESC LIMIT 1) AS stage
                 FROM assignments a
                 JOIN projects p ON p.id = a.project_id
                 JOIN companies c ON c.id = p.company_id
                WHERE a.student_id=%s AND a.status <> 'cancelled'
                ORDER BY a.assigned_at DESC""", (g.user["id"],))
        for row in pending:
            row["stage_text"] = STAGE_TEXT.get(
                row["stage"], "not submitted yet" if not row["stage"]
                else row["stage"].replace("_", " "))

    return render_template(
        "student/portfolio.html", profile=profile_of(g.user["id"]),
        work=rows, summary=summarise(rows), owner=True, today=date.today(),
        pending=pending,
        certificates=query(
            """SELECT * FROM portfolio_certificates
                WHERE student_id=%s ORDER BY issued_at DESC""", (g.user["id"],)))


@portfolio_bp.route("/student/portfolio/share", methods=["POST"])
@role_required("student")
def share():
    """Turn the public link on or off. Off revokes the old link for good."""
    profile = profile_of(g.user["id"])
    if not profile:
        abort(404)

    if profile["portfolio_public"]:
        execute("""UPDATE student_profiles
                      SET portfolio_public=FALSE, portfolio_token=NULL
                    WHERE user_id=%s""", (g.user["id"],))
        flash("Your portfolio is private again. The old link no longer works.",
              "success")
    else:
        execute("""UPDATE student_profiles
                      SET portfolio_public=TRUE, portfolio_token=%s
                    WHERE user_id=%s""", (secrets.token_urlsafe(24), g.user["id"]))
        flash("Public link created. Anyone holding it can see your finished work "
              "— and nothing else.", "success")

    return redirect(url_for("portfolio.mine"))


@portfolio_bp.route("/student/portfolio/headline", methods=["POST"])
@role_required("student")
def headline():
    execute("UPDATE student_profiles SET headline=%s WHERE user_id=%s",
            ((request.form.get("headline") or "").strip()[:160] or None,
             g.user["id"]))
    flash("Saved.", "success")
    return redirect(url_for("portfolio.mine"))


# ------------------------------------------------------------ public view

@portfolio_bp.route("/p/<token>")
def public(token):
    profile = query(
        """SELECT sp.*, u.id AS user_id, u.fullname, u.created_at AS joined_at,
                  f.name AS field_name, uni.name AS university_name
             FROM student_profiles sp
             JOIN users u ON u.id = sp.user_id
             LEFT JOIN fields f ON f.id = sp.field_id
             LEFT JOIN universities uni ON uni.id = sp.university_id
            WHERE sp.portfolio_token=%s AND sp.portfolio_public
              AND u.status='active'""", (token,), one=True)
    if not profile:
        abort(404)

    rows = completed_work(profile["user_id"])
    return render_template("student/portfolio.html", profile=profile, work=rows,
                           summary=summarise(rows), owner=False,
                           today=date.today(), certificates=[], pending=[])


# ---------------------------------------------------- consolidated record

@portfolio_bp.route("/student/portfolio/certificate", methods=["POST"])
@role_required("student")
def issue():
    """Freeze the current record into a numbered, printable document.

    The snapshot matters: a student may finish more work next month, and a
    certificate handed to an employer today should still say what it said
    today. Verification reads the snapshot, not the live tables.
    """
    rows = completed_work(g.user["id"])
    if not rows:
        flash("You have no completed projects yet, so there is nothing to "
              "certify. Finish a placement first.", "error")
        return redirect(url_for("portfolio.mine"))

    summary = summarise(rows)
    reference = "PX-" + secrets.token_hex(5).upper()

    snapshot = {
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "student": {
            "name": g.user["fullname"],
            "field": (profile_of(g.user["id"]) or {}).get("field_name"),
        },
        "summary": {
            "projects": summary["projects"],
            "companies": summary["companies"],
            "fields": summary["fields"],
            "skills": summary["skills"],
        },
        "projects": [
            {
                "title": r["title"],
                "company": r["company_name"],
                "field": r["field_name"],
                "difficulty": r["difficulty"],
                "started": r["assigned_at"].isoformat() if r["assigned_at"] else None,
                "completed": r["completed_at"].isoformat() if r["completed_at"] else None,
                "supervisor": r["lecturer_name"],
                "university": r["university_name"],
                "worked_as": r["worked_as"],
                "versions": r["version_count"],
                "files": r["file_count"],
                "certificate": r["certificate_number"],
            }
            for r in rows
        ],
    }

    execute("""INSERT INTO portfolio_certificates
               (student_id, reference, project_count, snapshot)
               VALUES (%s,%s,%s,%s)""",
            (g.user["id"], reference, len(rows), json.dumps(snapshot)))

    flash(f"Certificate {reference} issued, covering {len(rows)} "
          f"project{'' if len(rows) == 1 else 's'}.", "success")
    return redirect(url_for("portfolio.certificate", reference=reference))


@portfolio_bp.route("/certificate/<reference>")
def certificate(reference):
    """The printable document. Public by design — a certificate nobody can
    open is not a certificate."""
    row = query(
        """SELECT pc.*, u.fullname FROM portfolio_certificates pc
             JOIN users u ON u.id = pc.student_id
            WHERE pc.reference=%s""", (reference,), one=True)
    if not row:
        abort(404)

    snapshot = row["snapshot"]
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)

    return render_template("student/certificate.html", cert=row,
                           snap=snapshot, revoked=bool(row["revoked_at"]))


@portfolio_bp.route("/verify", methods=["GET", "POST"])
def verify():
    """Anyone with a reference number can check it here, with no account."""
    result, searched = None, ""
    if request.method == "POST":
        searched = (request.form.get("reference") or "").strip().upper()
        if searched:
            result = query(
                """SELECT pc.reference, pc.project_count, pc.issued_at,
                          pc.revoked_at, u.fullname
                     FROM portfolio_certificates pc
                     JOIN users u ON u.id = pc.student_id
                    WHERE upper(pc.reference)=%s""", (searched,), one=True)
            if not result:
                result = query(
                    """SELECT ce.certificate_number AS reference, 1 AS project_count,
                              ce.issued_at, NULL::timestamptz AS revoked_at,
                              u.fullname, p.title AS project_title
                         FROM certificates ce
                         JOIN users u ON u.id = ce.student_id
                         JOIN projects p ON p.id = ce.project_id
                        WHERE upper(ce.certificate_number)=%s""",
                    (searched,), one=True)

    return render_template("public/verify.html", result=result, searched=searched)
