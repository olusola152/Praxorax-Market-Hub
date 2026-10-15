"""Project presentations — the rules, kept away from the routes.

A presentation is one appointment hung off a placement. The student presents
the work; the company that owns the brief watches and decides; the supervising
lecturer sits in. Three different people, three different calendars, so the
slot has to be proposed, agreed, and then recorded — the call itself is the
short part.

What lives here and what does not:

  * Here: who is invited, who may confirm, who may record the outcome, whether
    a slot clashes, and the room name.
  * Not here: the video itself. That is a room on a video server, embedded in
    the page. Nothing that matters is stored inside it, so swapping Jitsi for
    Zoom or Meet changes one field and breaks nothing.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app, url_for

from db import execute, query

# A slot cannot be proposed for the past, and nobody can agree to something
# starting in the next few minutes, so there is a floor. It is configurable
# because the right value in production is a nuisance when you are walking a
# client through the whole flow in one sitting — see MIN_NOTICE_MINUTES.
MIN_NOTICE_FALLBACK = timedelta(minutes=15)

# How long after the start time the room stays open. People are late, calls
# overrun, and a room that locks on the dot is a support ticket.
GRACE_BEFORE = timedelta(minutes=20)
GRACE_AFTER = timedelta(minutes=60)

STATUS_LABEL = {
    "proposed": "Awaiting agreement",
    "confirmed": "Confirmed",
    "live": "In progress",
    "held": "Held",
    "missed": "Not held",
    "cancelled": "Cancelled",
}

OUTCOME_LABEL = {
    "passed": "Accepted",
    "rework": "Needs rework",
    "undecided": "No decision recorded",
}

PART_LABEL = {
    "presenter": "Presenting",
    "host": "Host",
    "observer": "Attending",
}


def now():
    return datetime.now(timezone.utc)


def min_notice():
    """How far ahead a session must start, as a timedelta."""
    try:
        minutes = current_app.config["MIN_NOTICE_MINUTES"]
    except Exception:            # outside an app context, use the default
        return MIN_NOTICE_FALLBACK
    return timedelta(minutes=max(int(minutes), 0))


def too_soon(starts_at):
    """True when a proposed slot is inside the notice period.

    With the notice set to 0 this still refuses a time in the past — booking
    backwards is a mistake at any setting, not a thing to allow for demos.
    """
    return starts_at < now() + min_notice()


def earliest():
    """The soonest a session may start, for the form's own `min` and label.

    Rounded up to the next whole minute: a picker cannot express seconds, so
    an un-rounded value would mark a time as allowed that the server then
    refuses by a few seconds.
    """
    moment = now() + min_notice()
    if moment.second or moment.microsecond:
        moment = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return moment


def notice_message():
    """The refusal, phrased for whatever the notice is set to."""
    minutes = int(min_notice().total_seconds() // 60)
    if minutes == 0:
        return "Choose a time in the future."
    if minutes == 1:
        return "Choose a time at least a minute from now."
    return f"Choose a time at least {minutes} minutes from now."


# --------------------------------------------------------------- local time
#
# Everything is stored in UTC. A <input type="datetime-local"> has no timezone
# at all, so the string a lecturer types is read as local time and converted
# once, here. Doing it anywhere else is how a 2pm defence becomes 3pm.

def local_zone():
    try:
        return ZoneInfo(current_app.config.get("TIMEZONE") or "UTC")
    except Exception:            # a bad TIMEZONE should not break scheduling
        return timezone.utc


def parse_local(value):
    """'2026-10-15T14:30' in the site's timezone -> an aware UTC datetime."""
    text = (value or "").strip().replace(" ", "T")
    if not text:
        return None
    try:
        naive = datetime.fromisoformat(text)
    except ValueError:
        return None
    if naive.tzinfo is not None:
        return naive.astimezone(timezone.utc)
    return naive.replace(tzinfo=local_zone()).astimezone(timezone.utc)


def to_local(value):
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(local_zone())


def form_value(value):
    """A stored time back into the format the date picker expects."""
    local = to_local(value)
    return local.strftime("%Y-%m-%dT%H:%M") if local else ""


# ------------------------------------------------------------------ the room

def new_room_name(assignment_id):
    """An unguessable room on the video server.

    The placement id is in there so a room can be traced back to a project
    when someone reports a problem, but the random half is what keeps a
    stranger from walking into a defence by typing a plausible name.
    """
    return f"praxorax-{assignment_id}-{secrets.token_urlsafe(12)}"


def valid_external_url(value):
    """A pasted meeting link, or None if it is not one.

    Deliberately narrow. These links are rendered as something people click,
    so anything but https to a known meeting host is refused rather than
    cleaned up — a half-understood link is worse than no link.
    """
    value = (value or "").strip()
    if not value or len(value) > 500:
        return None
    if not re.match(r"^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}/", value):
        return None
    host = value.split("/")[2].lower()
    allowed = ("zoom.us", "teams.microsoft.com", "teams.live.com",
               "meet.google.com", "whereby.com", "meet.jit.si", "webex.com")
    if host in allowed or any(host.endswith("." + a) for a in allowed):
        return value
    return None


def join_window(row):
    """Whether the room should open, and why not when it should not."""
    if row["status"] in ("held", "missed", "cancelled"):
        return False, "This session is over."
    if row["status"] == "proposed":
        return False, "The time has not been agreed yet."

    start = row["starts_at"]
    ends = start + timedelta(minutes=row["duration_mins"])
    moment = now()

    if moment < start - GRACE_BEFORE:
        return False, f"The room opens 20 minutes before {fmt(start)}."
    if moment > ends + GRACE_AFTER:
        return False, "The room has closed."
    return True, ""


def fmt(value):
    """One date format for the whole feature, so nothing reads differently."""
    local = to_local(value)
    return local.strftime("%a %d %b %Y, %H:%M") if local else ""


# ------------------------------------------------------------- who is invited

def chain_for(assignment_id):
    """The people on a placement, and nothing else.

    An independent student has no lecturer, so the room is the student and the
    company. That is a two-person call, not a broken three-person one.
    """
    return query(
        """SELECT asg.id AS assignment_id, asg.student_id, asg.lecturer_id,
                  asg.status AS assignment_status,
                  p.id AS project_id, p.title, p.deadline,
                  co.id AS company_id, co.user_id AS company_user_id,
                  co.name AS company_name,
                  stu.fullname AS student_name, stu.email AS student_email,
                  lec.fullname AS lecturer_name,
                  uni.id AS university_id, uni.name AS university_name
             FROM assignments asg
             JOIN projects p ON p.id = asg.project_id
             JOIN companies co ON co.id = p.company_id
             JOIN users stu ON stu.id = asg.student_id
             LEFT JOIN users lec ON lec.id = asg.lecturer_id
             LEFT JOIN lecturer_profiles lp ON lp.user_id = asg.lecturer_id
             LEFT JOIN universities uni ON uni.id = lp.university_id
            WHERE asg.id = %s""", (assignment_id,), one=True)


def invite_list(chain):
    """(user_id, part) for everyone who belongs in the room.

    The company hosts because the company decides. The student presents. A
    lecturer observes — they supervise the work, they do not accept it on the
    company's behalf.
    """
    people = [(chain["student_id"], "presenter"),
              (chain["company_user_id"], "host")]
    if chain["lecturer_id"]:
        people.append((chain["lecturer_id"], "observer"))
    return [(uid, part) for uid, part in people if uid]


def add_attendees(presentation_id, chain, proposer_id):
    """Write the invitations.

    Whoever proposed the slot has agreed to it by proposing it, so their own
    response is recorded as accepted rather than left pending — otherwise the
    page would ask them to confirm their own suggestion.
    """
    for user_id, part in invite_list(chain):
        accepted = user_id == proposer_id
        execute(
            """INSERT INTO presentation_attendees
               (presentation_id, user_id, part, response, responded_at)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (presentation_id, user_id) DO NOTHING""",
            (presentation_id, user_id, part,
             "accepted" if accepted else "pending",
             now() if accepted else None))


def attendees(presentation_id):
    return query(
        """SELECT pa.*, u.fullname, u.role, u.email
             FROM presentation_attendees pa
             JOIN users u ON u.id = pa.user_id
            WHERE pa.presentation_id = %s
            ORDER BY CASE pa.part WHEN 'presenter' THEN 1 WHEN 'host' THEN 2
                                  ELSE 3 END, u.fullname""",
        (presentation_id,))


def my_part(presentation_id, user_id):
    """The signed-in person's row, or None when they are not invited.

    This is the access check for the whole feature. An admin is handled by the
    caller; everyone else is either on the attendee list or is not in the room.
    """
    return query(
        """SELECT * FROM presentation_attendees
            WHERE presentation_id=%s AND user_id=%s""",
        (presentation_id, user_id), one=True)


# ------------------------------------------------------------------ fetching

def get(presentation_id):
    return query(
        """SELECT pr.*, asg.student_id, asg.lecturer_id, asg.project_id,
                  asg.status AS assignment_status,
                  p.title, p.deadline, co.id AS company_id,
                  co.user_id AS company_user_id, co.name AS company_name,
                  stu.fullname AS student_name,
                  lec.fullname AS lecturer_name,
                  lp.university_id,
                  proposer.fullname AS proposed_by_name,
                  proposer.role AS proposed_by_role,
                  decider.fullname AS outcome_by_name
             FROM presentations pr
             JOIN assignments asg ON asg.id = pr.assignment_id
             JOIN projects p ON p.id = asg.project_id
             JOIN companies co ON co.id = p.company_id
             JOIN users stu ON stu.id = asg.student_id
             JOIN users proposer ON proposer.id = pr.proposed_by
             LEFT JOIN users lec ON lec.id = asg.lecturer_id
             LEFT JOIN users decider ON decider.id = pr.outcome_by
             LEFT JOIN lecturer_profiles lp ON lp.user_id = asg.lecturer_id
            WHERE pr.id = %s""", (presentation_id,), one=True)


def for_assignment(assignment_id):
    return query(
        """SELECT pr.*, proposer.fullname AS proposed_by_name
             FROM presentations pr
             JOIN users proposer ON proposer.id = pr.proposed_by
            WHERE pr.assignment_id = %s
            ORDER BY pr.starts_at DESC""", (assignment_id,))


def mine(user_id, upcoming_only=False):
    """Every session this person is invited to, soonest first."""
    clause = ("AND pr.status IN ('proposed','confirmed','live')"
              if upcoming_only else "")
    return query(
        f"""SELECT pr.*, pa.part, pa.response, pa.joined_at,
                   p.title, co.name AS company_name,
                   stu.fullname AS student_name
              FROM presentation_attendees pa
              JOIN presentations pr ON pr.id = pa.presentation_id
              JOIN assignments asg ON asg.id = pr.assignment_id
              JOIN projects p ON p.id = asg.project_id
              JOIN companies co ON co.id = p.company_id
              JOIN users stu ON stu.id = asg.student_id
             WHERE pa.user_id = %s {clause}
             ORDER BY CASE WHEN pr.status IN ('proposed','confirmed','live')
                           THEN 0 ELSE 1 END, pr.starts_at""",
        (user_id,))


def for_university(university_id):
    """Every defence by a student of this institution.

    A university admin is not in the room — they answer for their students, so
    they need the record, not a seat. Their list is built from the lecturer's
    institution rather than from the attendee table.
    """
    return query(
        """SELECT pr.*, 'observer' AS part, 'accepted' AS response,
                  NULL::timestamptz AS joined_at,
                  p.title, co.name AS company_name,
                  stu.fullname AS student_name
             FROM presentations pr
             JOIN assignments asg ON asg.id = pr.assignment_id
             JOIN projects p ON p.id = asg.project_id
             JOIN companies co ON co.id = p.company_id
             JOIN users stu ON stu.id = asg.student_id
             JOIN lecturer_profiles lp ON lp.user_id = asg.lecturer_id
            WHERE lp.university_id = %s
            ORDER BY CASE WHEN pr.status IN ('proposed','confirmed','live')
                          THEN 0 ELSE 1 END, pr.starts_at""",
        (university_id,))


def for_platform():
    """Everything, for an administrator looking into a dispute."""
    return query(
        """SELECT pr.*, 'observer' AS part, 'accepted' AS response,
                  NULL::timestamptz AS joined_at,
                  p.title, co.name AS company_name,
                  stu.fullname AS student_name
             FROM presentations pr
             JOIN assignments asg ON asg.id = pr.assignment_id
             JOIN projects p ON p.id = asg.project_id
             JOIN companies co ON co.id = p.company_id
             JOIN users stu ON stu.id = asg.student_id
            ORDER BY CASE WHEN pr.status IN ('proposed','confirmed','live')
                          THEN 0 ELSE 1 END, pr.starts_at DESC
            LIMIT 200""")


def next_up(user_id):
    """The one session to put on a dashboard, or None."""
    rows = mine(user_id, upcoming_only=True)
    return rows[0] if rows else None


# ------------------------------------------------------------------- clashes

def clash(assignment_id, starts_at, duration_mins, ignore_id=None):
    """Another live session for this placement overlapping the proposed slot.

    Only checked within the placement. Two different students presenting at
    once is normal — the company sends different people, or watches twice.
    """
    ends = starts_at + timedelta(minutes=duration_mins)
    rows = query(
        """SELECT id, starts_at, duration_mins FROM presentations
            WHERE assignment_id=%s AND status IN ('proposed','confirmed','live')
              AND (%s IS NULL OR id <> %s)""",
        (assignment_id, ignore_id, ignore_id))
    for row in rows:
        other_end = row["starts_at"] + timedelta(minutes=row["duration_mins"])
        if starts_at < other_end and row["starts_at"] < ends:
            return row
    return None


# ------------------------------------------------------------- state changes

def _touch(presentation_id):
    execute("UPDATE presentations SET updated_at=NOW() WHERE id=%s",
            (presentation_id,))


def create(assignment_id, proposer_id, title, agenda, starts_at,
           duration_mins, provider="jitsi", external_url=None):
    """One appointment, with its invitations. Returns the new id."""
    room = new_room_name(assignment_id) if provider == "jitsi" else None
    presentation_id = execute(
        """INSERT INTO presentations
           (assignment_id, proposed_by, title, agenda, starts_at,
            duration_mins, provider, room_name, external_url)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (assignment_id, proposer_id, title, agenda or None, starts_at,
         duration_mins, provider, room, external_url), returning=True)

    add_attendees(presentation_id, chain_for(assignment_id), proposer_id)
    return presentation_id


def respond(presentation_id, user_id, accepted, reason=None):
    """Record one person's answer, and move the session if that settles it."""
    execute(
        """UPDATE presentation_attendees
              SET response=%s, responded_at=NOW()
            WHERE presentation_id=%s AND user_id=%s""",
        ("accepted" if accepted else "declined", presentation_id, user_id))

    if not accepted:
        execute(
            """UPDATE presentations SET status='cancelled', decline_reason=%s,
                      updated_at=NOW()
                WHERE id=%s AND status IN ('proposed','confirmed')""",
            (reason or None, presentation_id))
        return "cancelled"

    # Confirmed once nobody is still deciding. A session waiting on one
    # person is not confirmed, however many have said yes.
    pending = query(
        """SELECT COUNT(*) AS n FROM presentation_attendees
            WHERE presentation_id=%s AND response='pending'""",
        (presentation_id,), one=True)["n"]
    if pending == 0:
        execute(
            """UPDATE presentations SET status='confirmed', updated_at=NOW()
                WHERE id=%s AND status='proposed'""", (presentation_id,))
        return "confirmed"
    _touch(presentation_id)
    return "waiting"


def reschedule(presentation_id, starts_at, duration_mins, actor_id):
    """Move the slot and ask everyone again.

    A new time is a new question, so every response but the mover's goes back
    to pending. Silently keeping an old yes would put someone in a room they
    never agreed to.
    """
    execute(
        """UPDATE presentations
              SET starts_at=%s, duration_mins=%s, status='proposed',
                  proposed_by=%s, decline_reason=NULL, updated_at=NOW()
            WHERE id=%s""",
        (starts_at, duration_mins, actor_id, presentation_id))
    execute(
        """UPDATE presentation_attendees
              SET response='pending', responded_at=NULL
            WHERE presentation_id=%s AND user_id <> %s""",
        (presentation_id, actor_id))
    execute(
        """UPDATE presentation_attendees
              SET response='accepted', responded_at=NOW()
            WHERE presentation_id=%s AND user_id=%s""",
        (presentation_id, actor_id))


def mark_joined(presentation_id, user_id):
    """Attendance, written the first time someone opens the room.

    joined_at is set once and never overwritten; last_seen_at moves every
    time. Between them you can tell someone who arrived and stayed from
    someone who looked in at the end.
    """
    execute(
        """UPDATE presentation_attendees
              SET joined_at = COALESCE(joined_at, NOW()), last_seen_at = NOW()
            WHERE presentation_id=%s AND user_id=%s""",
        (presentation_id, user_id))
    execute(
        """UPDATE presentations
              SET status='live', started_at=COALESCE(started_at, NOW()),
                  updated_at=NOW()
            WHERE id=%s AND status='confirmed'""", (presentation_id,))


def record_outcome(presentation_id, outcome, notes, actor_id):
    execute(
        """UPDATE presentations
              SET status='held', outcome=%s, outcome_notes=%s, outcome_by=%s,
                  outcome_at=NOW(), ended_at=COALESCE(ended_at, NOW()),
                  updated_at=NOW()
            WHERE id=%s""",
        (outcome, notes or None, actor_id, presentation_id))


def mark_missed(presentation_id, notes, actor_id):
    execute(
        """UPDATE presentations
              SET status='missed', outcome_notes=%s, outcome_by=%s,
                  outcome_at=NOW(), updated_at=NOW()
            WHERE id=%s""", (notes or None, actor_id, presentation_id))


def cancel(presentation_id, reason):
    execute(
        """UPDATE presentations
              SET status='cancelled', decline_reason=%s, updated_at=NOW()
            WHERE id=%s AND status IN ('proposed','confirmed','live')""",
        (reason or None, presentation_id))


# ---------------------------------------------------------------- permissions

def may_propose(user, chain):
    """Who may put a slot forward.

    The student, because it is their defence; the company, because it is their
    brief; the supervising lecturer, because they decide when the work is ready
    to be shown. Nobody else, including other lecturers at the same university.
    """
    if not user or not chain:
        return False
    if user["role"] == "admin":
        return True
    if user["role"] == "student":
        return chain["student_id"] == user["id"]
    if user["role"] == "lecturer":
        return chain["lecturer_id"] == user["id"]
    if user["role"] == "company":
        return chain["company_id"] == user.get("company_id")
    return False


def may_view(user, row, part=None):
    """Attendees see a session. So does the university above the lecturer.

    The university sits in the review chain and answers for its students, so
    it can see that a defence happened and what came of it — without being
    put in the room.
    """
    if not user or not row:
        return False
    if user["role"] == "admin":
        return True
    if part:
        return True
    if user["role"] == "university":
        from flask import g
        uni = g.get("university")
        return bool(uni and row.get("university_id") == uni["id"])
    return False


def may_decide(user, row, part=None):
    """Who records what the presentation came to.

    The company, because it is the company's judgement. An admin, to fix a
    session the company left open. Not the lecturer: a supervisor marking
    their own student's defence as accepted on the company's behalf is the one
    thing this record exists to prevent.
    """
    if not user or not row:
        return False
    if user["role"] == "admin":
        return True
    if user["role"] == "company":
        return row["company_id"] == user.get("company_id")
    return False


def may_cancel(user, row, part=None):
    """Whoever proposed it, the company, or an admin."""
    if not user or not row:
        return False
    if user["role"] == "admin":
        return True
    if row["proposed_by"] == user["id"]:
        return True
    return user["role"] == "company" and row["company_id"] == user.get("company_id")


# ------------------------------------------------------------- notifications

def room_url(presentation_id):
    return url_for("presentations.room", presentation_id=presentation_id)
