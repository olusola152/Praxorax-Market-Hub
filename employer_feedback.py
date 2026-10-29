"""What the company thought of the student, once the work is signed off.

The platform's whole claim is that somebody is answerable for a student's
record. Completion proves the work happened; this says how it went, and it
means something only because of who may write it: the company that posted
the brief, from the account that approved the submission, against a
placement that is finished. A reference a graduate types in themselves
carries none of that, which is why this is the one thing on the site that
can fairly be called verified.

The competencies live here rather than in the template so the form, the
validation, the stored columns and every page that displays a score cannot
drift apart. Adding a fifth is a migration plus one line in this tuple.
"""
import logging

from db import execute, query

log = logging.getLogger(__name__)

#: Reads are guarded; writes are not. Code reaches a server before its
#: migration does — that is the normal order of a deploy — and a page that
#: merely *displays* feedback should degrade to showing none rather than
#: returning a 500. A write is the opposite case: silently swallowing a
#: company's saved rating and telling them it worked is worse than an error,
#: so save() and set_public() are left to fail loudly.
_warned = False


def _guarded(fn, fallback):
    global _warned
    try:
        return fn()
    except Exception as exc:
        if not _warned:
            log.warning("employer feedback unavailable (%s) — has "
                        "database/migration_v13.sql been run?", exc)
            _warned = True
        return fallback

#: (column, label, what the company is being asked). The column names match
#: employer_feedback exactly — the save below builds its SQL from them, so a
#: typo here fails loudly at insert rather than silently storing nothing.
COMPETENCIES = (
    ("communication", "Communication",
     "Kept you informed, asked when something was unclear, wrote clearly."),
    ("problem_solving", "Problem solving",
     "Worked out what the brief needed and found a way through the hard parts."),
    ("quality", "Quality of work",
     "The deliverable itself: correct, complete, and fit to use."),
    ("professionalism", "Professionalism",
     "Met the dates agreed, took feedback well, behaved like a colleague."),
)

KEYS = tuple(k for k, _, _ in COMPETENCIES)

#: Long enough to say something, short enough that nobody pastes an essay.
COMMENT_MAX = 1500
COMMENT_MIN = 20


def parse(form):
    """(scores, comment, errors) from a submitted form.

    Returns errors rather than raising: the company should get the form back
    with everything they already typed, not a stack trace or a blank page.
    """
    scores, errors = {}, []

    for key, label, _ in COMPETENCIES:
        raw = (form.get(key) or "").strip()
        if not raw:
            errors.append(f"Give a score for {label.lower()}.")
            continue
        try:
            value = int(raw)
        except ValueError:
            errors.append(f"{label} must be a number from 1 to 5.")
            continue
        if not 1 <= value <= 5:
            errors.append(f"{label} must be from 1 to 5.")
            continue
        scores[key] = value

    comment = (form.get("comment") or "").strip()
    if len(comment) < COMMENT_MIN:
        errors.append(
            "Write a sentence or two about the work — at least "
            f"{COMMENT_MIN} characters. The scores alone tell an employer "
            "reading this nothing about what the student actually did.")
    elif len(comment) > COMMENT_MAX:
        errors.append(f"Keep the comment under {COMMENT_MAX} characters.")

    return scores, comment, errors


def save(assignment_id, author_id, scores, comment):
    """Write the feedback for a placement, or replace what is there.

    ON CONFLICT rather than an existence check, because two people at the
    same company submitting the form at once would otherwise both pass the
    check and one would hit the unique constraint as a 500.
    """
    columns = ", ".join(KEYS)
    placeholders = ", ".join(["%s"] * len(KEYS))
    updates = ", ".join(f"{k}=EXCLUDED.{k}" for k in KEYS)

    execute(
        f"""INSERT INTO employer_feedback
                (assignment_id, author_id, {columns}, comment)
            VALUES (%s, %s, {placeholders}, %s)
            ON CONFLICT (assignment_id) DO UPDATE
               SET {updates},
                   comment = EXCLUDED.comment,
                   author_id = EXCLUDED.author_id,
                   created_at = NOW()""",
        (assignment_id, author_id, *[scores[k] for k in KEYS], comment))


def for_assignment(assignment_id):
    """The feedback on one placement, or None."""
    return _guarded(
        lambda: query("SELECT * FROM employer_feedback WHERE assignment_id = %s",
                      (assignment_id,), one=True),
        None)


def with_feedback(assignment_ids):
    """Which of these placements already have feedback, as a set.

    One query for a page full of students rather than one per row.
    """
    ids = [int(i) for i in assignment_ids if i]
    if not ids:
        return set()
    rows = _guarded(
        lambda: query("""SELECT assignment_id FROM employer_feedback
                          WHERE assignment_id = ANY(%s)""", (ids,)),
        [])
    return {r["assignment_id"] for r in rows}


def for_student(student_id, public_only=False):
    """Every piece of feedback this student has, keyed by assignment.

    public_only is what the difference between a student's own Praxfolio and
    the link they send an employer comes down to: the student sees all of it
    and decides, one by one, what a stranger sees.
    """
    rows = _guarded(
        lambda: query(
            f"""SELECT ef.*, p.title AS project_title, c.name AS company_name
                  FROM employer_feedback ef
                  JOIN assignments a ON a.id = ef.assignment_id
                  JOIN projects p ON p.id = a.project_id
                  JOIN companies c ON c.id = p.company_id
                 WHERE a.student_id = %s
                   {"AND ef.is_public" if public_only else ""}""",
            (student_id,)),
        [])
    return {r["assignment_id"]: r for r in rows}


def set_public(assignment_id, student_id, public):
    """Show or hide one piece of feedback on the public Praxfolio.

    Scoped by student_id in the WHERE clause rather than checked first, so a
    student cannot flip somebody else's feedback by guessing an assignment
    id. Returns whether a row actually changed — RETURNING rather than a
    rowcount, because execute() hands back a value only when asked.
    """
    return execute(
        """UPDATE employer_feedback ef
              SET is_public = %s
             FROM assignments a
            WHERE a.id = ef.assignment_id
              AND ef.assignment_id = %s
              AND a.student_id = %s
        RETURNING ef.assignment_id""",
        (bool(public), assignment_id, student_id), returning=True) is not None


def summarise(feedback_by_assignment):
    """Averages across everything given, for the top of a Praxfolio.

    None when there is nothing yet, so a template can tell "no feedback"
    apart from "all zeros", which are not the same thing and should not
    render the same way.
    """
    rows = list(feedback_by_assignment.values())
    if not rows:
        return None

    out = {"count": len(rows)}
    for key, label, _ in COMPETENCIES:
        out[key] = round(sum(r[key] for r in rows) / len(rows), 1)
    out["overall"] = round(sum(float(r["overall"]) for r in rows) / len(rows), 1)
    return out
