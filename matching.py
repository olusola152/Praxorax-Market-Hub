"""Scoring a brief against what a student can do.

Tag overlap, nothing clever: the share of a project's required skills that the
student has, nudged by how much of the student's own skill set is used. It is
transparent, it needs no external service, and a student can see exactly why a
number came out the way it did.

The PRD's semantic matching would sit behind the same function — swap the body
of `score` and everything calling it keeps working.
"""
from db import query

# Below this, a brief is not worth showing as a "match".
THRESHOLD = 0.30


def score(student_skill_ids, project_skill_ids):
    """0.0 to 1.0. Weighted toward covering what the project asks for."""
    wanted = set(project_skill_ids or ())
    has = set(student_skill_ids or ())
    if not wanted or not has:
        return 0.0

    covered = len(wanted & has) / len(wanted)          # how much of the brief
    union = len(wanted | has)
    jaccard = len(wanted & has) / union if union else 0.0
    return round(0.7 * covered + 0.3 * jaccard, 4)


def label(value):
    if value >= 0.8:
        return "strong match"
    if value >= 0.5:
        return "good match"
    if value >= THRESHOLD:
        return "partial match"
    return ""


def student_skill_ids(user_id):
    return [r["skill_id"] for r in query(
        "SELECT skill_id FROM student_skills WHERE user_id=%s", (user_id,))]


def project_skill_map(project_ids):
    """{project_id: [skill_id, ...]} for a page of briefs, in one query."""
    if not project_ids:
        return {}
    rows = query(
        "SELECT project_id, skill_id FROM project_skills WHERE project_id = ANY(%s)",
        (list(project_ids),))
    out = {}
    for row in rows:
        out.setdefault(row["project_id"], []).append(row["skill_id"])
    return out


def annotate(projects, user_id):
    """Attach `match` and `match_label` to each project row, in place."""
    mine = student_skill_ids(user_id)
    if not mine:
        for p in projects:
            p["match"], p["match_label"] = None, ""
        return projects

    per_project = project_skill_map([p["id"] for p in projects])
    for p in projects:
        value = score(mine, per_project.get(p["id"], []))
        p["match"] = value
        p["match_label"] = label(value)
    return projects
