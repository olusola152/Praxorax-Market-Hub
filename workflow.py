"""Shared rules: subscription expiry, notifications, and the review chain."""

from datetime import date

from flask import current_app, g, url_for

import mailer
from db import execute, query

# Where work goes next, and who is told about it.
NEXT_STAGE = {
    "with_lecturer": "with_university",
    "with_university": "with_company",
}

STAGE_LABEL = {
    "with_lecturer": "With the lecturer",
    "with_university": "With the university",
    "with_company": "With the company",
    "approved": "Approved",
    "revision": "Correction requested",
}


# ------------------------------------------------------------ subscriptions

def effective_status(status, until):
    """A subscription past its end date is expired, whatever the column says.

    Checked on read rather than by a nightly job, so nothing depends on a
    scheduler being alive. A free trial expires the same way a paid term does.
    """
    if status in ("active", "trial") and until and until < date.today():
        return "expired"
    return status


def subscription_live(status, until):
    """Trial and paid access are the same thing while they last.

    Keeping them equal here means no feature has to ask which one it is
    looking at — a trial that quietly did less would be a poor trial.
    """
    if current_app.config.get("DEMO_MODE"):
        return True
    return effective_status(status, until) in ("active", "trial")


def trial_days_left(status, until):
    """Whole days remaining, or None when this is not a running trial."""
    if status != "trial" or not until:
        return None
    return max((until - date.today()).days, 0)


def expire_lapsed():
    """Write the expiry back so admin lists and reports agree with reality."""
    execute("""UPDATE universities SET subscription_status = 'expired'
                WHERE subscription_status IN ('active','trial')
                  AND subscribed_until IS NOT NULL
                  AND subscribed_until < CURRENT_DATE""")
    execute("""UPDATE companies SET subscription_status = 'expired'
                WHERE subscription_status IN ('active','trial')
                  AND subscribed_until IS NOT NULL
                  AND subscribed_until < CURRENT_DATE""")


# ------------------------------------------------------------ notifications

def notify(user_id, body, url=None, email=True):
    """Save an in-app alert, and email it unless the person opted out.

    The database row is written first and is never conditional on the email.
    Mail is best effort: if the server is down the alert is still waiting in
    the app.
    """
    if not user_id:
        return

    notification_id = execute(
        """INSERT INTO notifications (user_id, body, url)
           VALUES (%s,%s,%s) RETURNING id""",
        (user_id, body, url), returning=True)

    if not email or not mailer.configured():
        return

    person = query(
        """SELECT email, fullname, email_notifications FROM users
            WHERE id=%s AND status='active'""", (user_id,), one=True)
    if not person or not person["email_notifications"]:
        return

    sent = mailer.send(person["email"], person["fullname"],
                       mailer.subject_for(body, current_app.config["BRAND"]),
                       body, url)
    if sent:
        execute("UPDATE notifications SET emailed_at=NOW() WHERE id=%s",
                (notification_id,))


def notify_many(user_ids, body, url=None):
    for uid in {u for u in user_ids if u}:
        notify(uid, body, url)


def unread_count(user_id):
    row = query("SELECT COUNT(*) AS n FROM notifications WHERE user_id=%s AND read_at IS NULL",
                (user_id,), one=True)
    return row["n"] if row else 0


# ------------------------------------------------------------ review chain

def first_stage(lecturer_id):
    """Who receives a new submission.

    A student placed by a lecturer sends work up the chain as before. An
    independent student has no lecturer and no university, so the work goes
    straight to the company.
    """
    return "with_lecturer" if lecturer_id else "with_company"


def chain_people(assignment_id):
    """The four parties attached to one placement."""
    return query(
        """SELECT asg.student_id, asg.lecturer_id,
                  uni.admin_user_id AS university_id, uni.name AS university_name,
                  co.user_id AS company_user_id, co.name AS company_name,
                  p.id AS project_id, p.title
             FROM assignments asg
             JOIN projects p ON p.id = asg.project_id
             JOIN companies co ON co.id = p.company_id
             LEFT JOIN lecturer_profiles lp ON lp.user_id = asg.lecturer_id
             LEFT JOIN universities uni ON uni.id = lp.university_id
            WHERE asg.id = %s""", (assignment_id,), one=True)


def record_review(submission_id, action, comment, new_stage, milestone_id=None):
    """Write a decision into the trail.

    new_stage may be None, for a decision that comments on the work without
    moving it anywhere — signing off one phase, for instance, while the rest
    of the submission stays where it is.
    """
    execute(
        """INSERT INTO reviews
           (submission_id, reviewer_id, reviewer_role, action, comment, milestone_id)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (submission_id, g.user["id"], g.user["role"], action, comment or None,
         milestone_id))
    if new_stage:
        execute("UPDATE submissions SET stage=%s, updated_at=NOW() WHERE id=%s",
                (new_stage, submission_id))


def submission_for(submission_id):
    return query(
        """SELECT s.*, asg.id AS assignment_id, asg.student_id, asg.lecturer_id,
                  asg.project_id, p.title, p.company_id,
                  stu.fullname AS student_name,
                  lec.fullname AS lecturer_name,
                  lp.university_id,
                  co.user_id AS company_user_id, co.name AS company_name
             FROM submissions s
             JOIN assignments asg ON asg.id = s.assignment_id
             JOIN projects p ON p.id = asg.project_id
             JOIN companies co ON co.id = p.company_id
             JOIN users stu ON stu.id = asg.student_id
             LEFT JOIN users lec ON lec.id = asg.lecturer_id
             LEFT JOIN lecturer_profiles lp ON lp.user_id = asg.lecturer_id
            WHERE s.id = %s""", (submission_id,), one=True)


def history(submission_id):
    return query(
        """SELECT r.*, u.fullname, m.title AS phase_title, m.phase AS phase_number
             FROM reviews r
             JOIN users u ON u.id = r.reviewer_id
             LEFT JOIN milestones m ON m.id = r.milestone_id
            WHERE r.submission_id = %s ORDER BY r.created_at""", (submission_id,))


# ------------------------------------------------------------ project files

def submission_files(submission_id):
    """Every file attached to one submitted version, oldest first."""
    return query(
        """SELECT sf.*, u.fullname AS uploader_name
             FROM submission_files sf
             JOIN users u ON u.id = sf.uploaded_by
            WHERE sf.submission_id = %s
            ORDER BY sf.uploaded_at, sf.id""", (submission_id,))


def files_for_assignment(assignment_id):
    """The whole archive for a placement — every version, newest first."""
    return query(
        """SELECT sf.*, s.version, s.stage, s.submitted_at,
                  u.fullname AS uploader_name
             FROM submission_files sf
             JOIN submissions s ON s.id = sf.submission_id
             JOIN users u ON u.id = sf.uploaded_by
            WHERE s.assignment_id = %s
            ORDER BY s.version DESC, sf.id""", (assignment_id,))


def can_access_submission(sub):
    """Everyone on a placement's chain may read its files.

    That is the student who sent it, the lecturer supervising, the university
    that lecturer belongs to, the company that owns the brief, and any admin.
    An independent student's chain is just the student and the company.
    """
    if not sub or not g.get("user"):
        return False

    user = g.user
    role = user["role"]

    if role == "admin":
        return True
    if role == "student":
        return sub["student_id"] == user["id"]
    if role == "lecturer":
        return sub["lecturer_id"] == user["id"]
    if role == "company":
        return sub["company_id"] == user["company_id"]
    if role == "university":
        uni = g.get("university")
        return bool(uni and sub.get("university_id") == uni["id"])
    return False


def record_download(user_id, submission_id, file_id=None, kind="file"):
    """Keep a trail of who collected the work and when."""
    execute(
        """INSERT INTO file_downloads (file_id, submission_id, user_id, kind)
           VALUES (%s, %s, %s, %s)""", (file_id, submission_id, user_id, kind))


def download_log(submission_id):
    return query(
        """SELECT fd.created_at, fd.kind, u.fullname, u.role
             FROM file_downloads fd JOIN users u ON u.id = fd.user_id
            WHERE fd.submission_id = %s
            ORDER BY fd.created_at DESC LIMIT 50""", (submission_id,))
