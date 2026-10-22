"""When a student's profile is complete enough to be put in front of a company.

A student could apply for a brief with nothing on their profile but a name,
which left companies deciding on no evidence. This decides what "enough"
means and says plainly what is still missing, because a gate that refuses
without explaining is worse than no gate.

What is required is deliberately modest — a field of study, a level, a few
sentences about themselves and one skill. It is the minimum a company needs to
tell one applicant from another, not a CV. A GitHub link helps and is counted
as a suggestion rather than a requirement, because plenty of good students in
plenty of fields do not have one.
"""
from db import execute, query

BIO_MIN = 80          # characters; roughly two sentences


def profile_of(user_id):
    return query(
        """SELECT sp.*, f.name AS field_name,
                  (SELECT COUNT(*) FROM student_skills ss
                    WHERE ss.user_id = sp.user_id) AS skill_count
             FROM student_profiles sp
             LEFT JOIN fields f ON f.id = sp.field_id
            WHERE sp.user_id = %s""", (user_id,), one=True)


def missing(profile):
    """What still has to be filled in, in the words the form uses.

    Returns a list of (field, what to do) so a page can link straight to the
    thing that is wrong rather than saying "incomplete".
    """
    if not profile:
        return [("field_id", "Choose your field of study"),
                ("level", "Say what level you are at"),
                ("bio", "Write a short description of yourself"),
                ("skills", "List at least one skill")]

    gaps = []
    if not profile.get("field_id"):
        gaps.append(("field_id", "Choose your field of study"))
    if not (profile.get("level") or "").strip():
        gaps.append(("level", "Say what level you are at"))
    if len((profile.get("bio") or "").strip()) < BIO_MIN:
        gaps.append(("bio",
                     f"Write at least {BIO_MIN} characters about yourself — "
                     f"what you study and what you can build"))
    if not profile.get("skill_count"):
        gaps.append(("skills", "List at least one skill"))
    return gaps


def suggestions(profile):
    """Worth having, never required."""
    if not profile:
        return []
    tips = []
    if not (profile.get("github_url") or "").strip():
        tips.append("Add a GitHub link so a company can see your code")
    if not (profile.get("matric_no") or "").strip():
        tips.append("Add your matriculation number if your university is here")
    return tips


def is_complete(user_id):
    return not missing(profile_of(user_id))


def refresh_completion(user_id):
    """Stamp or clear completed_at after a profile is edited.

    The timestamp is set once and kept: it answers "when did this student
    become ready", which is worth knowing even if they later empty a field.
    It is cleared again only if the profile stops qualifying, so the prompt
    comes back.
    """
    profile = profile_of(user_id)
    done = not missing(profile)

    if done and profile and not profile.get("completed_at"):
        execute("""UPDATE student_profiles SET completed_at = NOW()
                    WHERE user_id = %s AND completed_at IS NULL""", (user_id,))
    elif not done and profile and profile.get("completed_at"):
        execute("""UPDATE student_profiles SET completed_at = NULL
                    WHERE user_id = %s""", (user_id,))
    return done
