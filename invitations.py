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


def signup_url(token):
    return url_for("auth.register", invite=token, _external=False)


# ------------------------------------------------------------------ claiming

def claim_for(user_id, email):
    """Turn every live invitation for this address into team membership.

    Called once, at signup. The new member lands as 'invited' rather than
    'active': they followed a link, which is not the same as having agreed to
    join, and the team page already knows how to show a pending invitation.

    Returns the teams they were invited to, so the signup message can say so.
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
        team = query("SELECT id, status FROM teams WHERE id=%s",
                     (row["team_id"],), one=True)
        if not team or team["status"] not in ("forming", "applied"):
            execute("UPDATE team_invitations SET status='expired' WHERE id=%s",
                    (row["id"],))
            continue

        execute(
            """INSERT INTO team_members (team_id, user_id, status)
               VALUES (%s,%s,'invited')
               ON CONFLICT (team_id, user_id) DO NOTHING""",
            (row["team_id"], user_id))
        execute(
            """UPDATE team_invitations
                  SET status='accepted', accepted_at=NOW(), accepted_by=%s
                WHERE id=%s""", (user_id, row["id"]))
        joined.append(row)

    return joined
