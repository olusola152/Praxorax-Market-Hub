"""Sending email.

Every in-app alert can also go out by email. The rules this follows:

  * Never block a request. Mail goes out on a background thread, so a slow or
    dead SMTP server cannot make a student wait for a page.
  * Never break the app. If mail is not configured, or the server refuses, the
    in-app notification is already saved and the failure is logged and dropped.
  * Never mail someone who said no. Each account carries a switch.

Supabase is not involved. Its email service only handles auth mail —
confirmations, magic links, password resets — and has no API for sending
arbitrary messages, so this talks to an SMTP server directly. Gmail, Zoho,
Brevo, Mailgun or your own domain all work; put the details in .env.
"""
import html
import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr

from flask import current_app

log = logging.getLogger(__name__)


def configured(app=None):
    cfg = (app or current_app).config
    return bool(cfg.get("MAIL_ENABLED") and cfg.get("MAIL_HOST")
                and cfg.get("MAIL_FROM"))


def _build(cfg, to_address, to_name, subject, body, url):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["BRAND"], cfg["MAIL_FROM"]))
    msg["To"] = formataddr((to_name or "", to_address))
    if cfg.get("MAIL_REPLY_TO"):
        msg["Reply-To"] = cfg["MAIL_REPLY_TO"]

    link = f"{cfg['BASE_URL'].rstrip('/')}{url}" if url else cfg["BASE_URL"]
    brand = cfg["BRAND"]

    # A blank line in the body means a new paragraph. Escaping the whole
    # thing into one <p> turned every multi-paragraph message into a wall.
    paragraphs = "".join(
        f'<p style="margin:0 0 18px;font-size:16px;line-height:1.55">'
        f'{html.escape(part.strip())}</p>'
        for part in body.split("\n\n") if part.strip())

    msg.set_content(
        f"{body}\n\n{link}\n\n--\n{brand}\n"
        f"To stop these emails, turn them off in your account settings.")

    msg.add_alternative(f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#F6F4EF;
  font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#17211C">
  <div style="max-width:520px;margin:0 auto;background:#fff;border:1px solid #E2DDD3;
       border-top:4px solid #1E4B3A;padding:28px">
    <p style="margin:0 0 20px;font-size:13px;letter-spacing:.14em;
         text-transform:uppercase;color:#6B7A72">{html.escape(brand)}</p>
    {paragraphs}
    <a href="{html.escape(link)}" style="display:inline-block;background:#1E4B3A;
       color:#fff;text-decoration:none;padding:11px 20px;font-size:14px">Open it</a>
    <p style="margin:26px 0 0;font-size:12px;color:#6B7A72;line-height:1.5">
      You are getting this because of activity on your {html.escape(brand)} account.
      Turn these off in your account settings at any time.</p>
  </div>
</body></html>""", subtype="html")
    return msg


def _deliver(cfg, msg):
    host, port = cfg["MAIL_HOST"], cfg["MAIL_PORT"]
    timeout = cfg.get("MAIL_TIMEOUT", 20)
    try:
        if cfg.get("MAIL_SSL"):
            server = smtplib.SMTP_SSL(host, port, timeout=timeout,
                                      context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
        with server:
            if cfg.get("MAIL_STARTTLS") and not cfg.get("MAIL_SSL"):
                server.starttls(context=ssl.create_default_context())
            if cfg.get("MAIL_USER"):
                server.login(cfg["MAIL_USER"], cfg["MAIL_PASSWORD"])
            server.send_message(msg)
        log.info("mail sent to %s", msg["To"])
        return True
    except Exception as exc:
        # The in-app alert is already saved, so a mail failure costs nothing
        # but the email itself. Log it and carry on.
        log.warning("mail to %s failed: %s", msg["To"], exc)
        return False


def send(to_address, to_name, subject, body, url=None, app=None):
    """Queue one message. Returns True if it was queued, not if it arrived."""
    app = app or current_app._get_current_object()
    if not configured(app) or not to_address:
        return False

    msg = _build(app.config, to_address, to_name, subject, body, url)

    if app.config.get("MAIL_SYNCHRONOUS"):      # tests want a straight answer
        return _deliver(app.config, msg)

    threading.Thread(target=_deliver, args=(app.config, msg), daemon=True).start()
    return True


def send_now(app, to_address, to_name, subject, body, url=None):
    """Send one message on this thread and say what happened.

    Everything else here is fire-and-forget on a background thread, which is
    right for alerts and useless for answering "is email actually working?".
    This waits, and hands back the server's own refusal so a person can act
    on it instead of guessing.

    Returns (sent, detail). detail is empty on success.
    """
    if not app.config.get("MAIL_ENABLED"):
        return False, "Email is switched off for this site (MAIL_ENABLED)."
    if not app.config.get("MAIL_HOST"):
        return False, "No mail server is configured (MAIL_HOST)."
    if not app.config.get("MAIL_FROM"):
        return False, "No sending address is configured (MAIL_FROM)."
    if not to_address:
        return False, "This account has no email address."

    msg = _build(app.config, to_address, to_name, subject, body, url)
    try:
        host, port = app.config["MAIL_HOST"], app.config["MAIL_PORT"]
        timeout = app.config.get("MAIL_TIMEOUT", 20)
        if app.config.get("MAIL_SSL"):
            server = smtplib.SMTP_SSL(host, port, timeout=timeout,
                                      context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
        with server:
            if app.config.get("MAIL_STARTTLS") and not app.config.get("MAIL_SSL"):
                server.starttls(context=ssl.create_default_context())
            if app.config.get("MAIL_USER"):
                server.login(app.config["MAIL_USER"], app.config["MAIL_PASSWORD"])
            server.send_message(msg)
        return True, ""
    except Exception as exc:
        log.warning("test mail to %s failed: %s", to_address, exc)
        return False, f"{type(exc).__name__}: {exc}"


def subject_for(body, brand):
    """A subject line from the alert text, cut at the first sentence."""
    first = body.split(". ")[0].strip().rstrip(".")
    if len(first) > 72:
        first = first[:69].rsplit(" ", 1)[0] + "…"
    return f"{first} - {brand}"


# --------------------------------------------------------------- welcome

WELCOME = {
    "student": (
        "Welcome to {brand}, where students do real work for real companies "
        "and leave with a record an employer can check.\n\n"
        "Here is how it goes. Companies post briefs — actual work they need "
        "done, with a deadline and a field of study. You apply for the ones "
        "that fit, send your work through the site, and it is reviewed before "
        "it is accepted. Every project you finish goes on your portfolio with "
        "a certificate carrying a reference anyone can verify.\n\n"
        "Two things to do now. Finish your profile — it is what a company "
        "sees when it decides between applicants, and you cannot apply until "
        "it is done. Then browse the open briefs.\n\n"
        "Students pay nothing here, ever."),

    "company": (
        "Welcome to {brand}, where companies get real work delivered by "
        "supervised students.\n\n"
        "You post a brief: work you actually need done, with a deadline and "
        "the skills it calls for. Universities bring their lecturers, who "
        "take briefs on and place their own students; students who joined "
        "independently apply to you directly. Either way the work comes back "
        "reviewed, and you decide whether it passes.\n\n"
        "One step before a brief can go live: we verify every company. Send "
        "your registration document from the Verification page and an "
        "administrator will look at it. You can draft briefs meanwhile."),

    "university": (
        "Welcome to {brand}, where your students get supervised experience "
        "on real company work.\n\n"
        "Your institution gets its own portal. You issue passcodes, your "
        "lecturers join with them and take on company briefs, and they place "
        "your students. Every submission passes through you before it reaches "
        "the company, so nothing leaves in your name unseen.\n\n"
        "One step first: we confirm every institution before its portal takes "
        "signups, because that portal carries your name and asks students for "
        "their matriculation numbers. Send us something that shows the "
        "institution is yours — a page on your own domain will usually do — "
        "and an administrator will look at it."),

    "lecturer": (
        "Welcome to {brand}. You are registered with your institution.\n\n"
        "Companies post real briefs with deadlines and required skills. "
        "Browse them, request the ones that suit your field, and once the "
        "company approves you can place your own students on them as "
        "practical coursework.\n\n"
        "Their work comes to you first. You review each phase, send it back "
        "for corrections if it needs them, and pass it up when it is ready."),

    "admin": (
        "Your {brand} administrator account is ready.\n\n"
        "Two things wait on you: verifying companies and institutions before "
        "they can trade on their names here, and activating subscriptions. "
        "The operations deck shows both, along with any work that has sat "
        "with one reviewer for more than a week."),
}

# Added to the two paying roles when a free period is actually on. Kept as
# one sentence rather than a second copy of every message, because two full
# sets drift apart the first time one of them is edited.
TRIAL_SENTENCE = {
    "company": ("Your free trial has started: {days} days of everything, with "
                "nothing to pay and no card needed."),
    "university": ("Your free trial has started: {days} days of everything, "
                   "with nothing to pay and no card needed."),
}


def send_team_invite(app, to_address, from_name, team_name, token):
    """Ask someone with no account to join a team.

    The only thing in the link is the token. It does not name the team or the
    address, so forwarding the mail is the only way to pass the invitation on.
    """
    if not configured(app):
        return False

    brand = app.config["BRAND"]
    body = (f"{from_name} has invited you to join the team \"{team_name}\" on "
            f"{brand}, where students take on real projects posted by companies "
            f"and get a verified record of the work.\n\n"
            f"You do not have an account yet. Create one with this address and "
            f"you will find the invitation waiting on your Teams page. It is "
            f"free for students, and the link below fills in the rest.")

    return send(to_address, None, f"{from_name} invited you to a team on {brand}",
                body, f"/register?invite={token}", app=app)


def send_welcome(app, to_address, to_name, role):
    """One message when an account is created, saying what to do next.

    Not a notification — there is no in-app equivalent and nothing to link to
    beyond the dashboard — so it is sent directly rather than through notify().
    """
    body = WELCOME.get(role)
    if not body or not configured(app):
        return False

    brand = app.config["BRAND"]
    body = body.format(brand=brand)

    days = app.config.get("TRIAL_DAYS", 0)
    if days and role in TRIAL_SENTENCE:
        body += "\n\n" + TRIAL_SENTENCE[role].format(days=days)

    return send(to_address, to_name, f"Welcome to {brand}", body, "/", app=app)
