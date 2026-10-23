"""Inviting someone to a team before they have an account.

The team page could only invite people already registered, which made it
useless for the thing students actually do: pull in a coursemate who has
never heard of the site. This holds the gap between "invited" and "has an
account", and closes it the moment they sign up.

There are deliberately two places an invitation can live, not one:

  * team_members, once there is a user row to point at. That is the real
    membership record and nothing here replaces it.
  * team_invitations, before that, keyed by email address.

The second converts into the first at signup and is then done with. Keeping
membership in one table means no part of the app has to ask both.
"""
import secrets
from datetime import datetime, timedelta, timezone

from flask import url_for

from db import execute, query, scalar

# Long enough that a pending invitation is not a standing gift, short enough
# that a stale address does not keep a seat on a team indefinitely.
INVITE_VALID_DAYS = 21


def new_token():
    return secrets.token_urlsafe(24)


def normalise(email):
    return (email or "").strip().lower()


# ------------------------------------------------------------------ creating

def pending_for_team(team_id):
    """Invitations sent to addresses that have not signed up yet."""
    return query(
        """SELECT ti.*, u.fullname AS invited_by_name
             FROM team_invitations ti
             JOIN users u ON u.id = ti.invited_by
            WHERE ti.team_id = %s AND ti.status = 'pending'
            ORDER BY ti.created_at""", (team_id,))


def pending_count(team_id):
    return scalar(
        """SELECT COUNT(*) FROM team_invitations
            WHERE team_id=%s AND status='pending' AND expires_at > NOW()""",
        (team_id,))


def invite_email(team_id, email, invited_by):
    """Create or refresh an invitation. Returns the row.

    Re-inviting the same address reuses the row and issues a fresh token, so
    a team lead who clicks twice sends one more email rather than leaving two
    live invitations that both have to be tracked.
    """
    email = normalise(email)
    expires = datetime.now(timezone.utc) + timedelta(days=INVITE_VALID_DAYS)
    token = new_token()

    execute(
        """INSERT INTO team_invitations
             (team_id, email, invited_by, token, expires_at)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (team_id, email) DO UPDATE
             SET token = EXCLUDED.token,
                 status = 'pending',
                 invited_by = EXCLUDED.invited_by,
                 created_at = NOW(),
                 expires_at = EXCLUDED.expires_at,
                 accepted_at = NULL,
                 accepted_by = NULL""",
        (team_id, email, invited_by, token, expires))

    return query(
        "SELECT * FROM team_invitations WHERE team_id=%s AND email=%s",
        (team_id, email), one=True)


def cancel(invitation_id, team_id):
    execute(
        """UPDATE team_invitations SET status='cancelled'
            WHERE id=%s AND team_id=%s AND status='pending'""",
        (invitation_id, team_id))


def by_token(token):
    return query(
        """SELECT ti.*, t.name AS team_name, u.fullname AS invited_by_name
             FROM team_invitations ti
             JOIN teams t ON t.id = ti.team_id
             JOIN users u ON u.id = ti.invited_by
            WHERE ti.token = %s""", (token,), one=True)


def live(row):
    """Whether an invitation can still be used."""
    if not row or row["status"] != "pending":
        return False
    expires = row["expires_at"]
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > datetime.now(timezone.utc)


def landing_url(token, external=False):
    """Where an invitation email points.

    Not the signup form. Somebody who has never heard of the site needs to
    read what it is before being asked for a password, so the link opens a
    page that explains the place and the team, and only then offers the form.
    """
    return url_for("invites.landing", token=token, _external=external)


def signup_url(token):
    return url_for("auth.register", invite=token, _external=False)


# ------------------------------------------------------------------ joining

#: A team is small on purpose: everybody on it is answerable for the work.
MAX_MEMBERS = 6


def team_open(team_id):
    """Whether this team can still take the person the invitation names.

    Three ways it cannot: the team is gone, it has moved past forming up, or
    it is full. Every one of them is somebody else's doing, so the caller
    reports it rather than failing the signup over it.
    """
    team = query("SELECT id, status FROM teams WHERE id=%s", (team_id,), one=True)
    if not team:
        return False, "That team no longer exists."
    if team["status"] not in ("forming", "applied"):
        return False, "That team has already started work and is closed to new members."

    seats = scalar(
        """SELECT COUNT(*) FROM team_members
            WHERE team_id=%s AND status IN ('active','invited')""", (team_id,))
    if seats >= MAX_MEMBERS:
        return False, f"That team is full ({MAX_MEMBERS} members)."
    return True, None


def place(row, user_id, status):
    """Write one invitation into membership and close the invitation."""
    execute(
        """INSERT INTO team_members (team_id, user_id, status, joined_at)
           VALUES (%s,%s,%s, CASE WHEN %s='active' THEN NOW() END)
           ON CONFLICT (team_id, user_id) DO UPDATE
             SET status = EXCLUDED.status,
                 joined_at = COALESCE(team_members.joined_at, EXCLUDED.joined_at)""",
        (row["team_id"], user_id, status, status))
    execute(
        """UPDATE team_invitations
              SET status='accepted', accepted_at=NOW(), accepted_by=%s
            WHERE id=%s""", (user_id, row["id"]))


# ------------------------------------------------------------------ claiming

def claim_for(user_id, email, accepted_token=None):
    """Turn every live invitation for this address into team membership.

    Called once, at signup. Two outcomes, and the difference matters:

      * The invitation they actually followed — the one whose token brought
        them to the signup form after they read the invitation page and chose
        to join — lands as 'active'. They have already said yes twice by then
        and being made to say it a third time on arrival is nonsense.
      * Any other invitation waiting for the same address lands as 'invited'.
        Nobody consented to those; they show up on the Teams page to accept
        or decline like any other.

    Returns one row per team, each carrying 'active' so the caller can tell
    the two apart when it writes to the person and to whoever invited them.
    """
    email = normalise(email)
    rows = query(
        """SELECT ti.*, t.name AS team_name
             FROM team_invitations ti
             JOIN teams t ON t.id = ti.team_id
            WHERE ti.email = %s AND ti.status = 'pending'
              AND ti.expires_at > NOW()""", (email,))

    joined = []
    for row in rows:
        # The team may have filled up or been disbanded since. Skip quietly
        # rather than failing a signup over somebody else's team.
        ok, _why = team_open(row["team_id"])
        if not ok:
            execute("UPDATE team_invitations SET status='expired' WHERE id=%s",
                    (row["id"],))
            continue

        straight_in = bool(accepted_token) and row["token"] == accepted_token
        place(row, user_id, "active" if straight_in else "invited")
        joined.append(dict(row, active=straight_in))

    return joined
