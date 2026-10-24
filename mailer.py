"""Sending email.

Every in-app alert can also go out by email. The rules this follows:

  * Never block a request. Mail goes out on a background thread, so a slow or
    dead SMTP server cannot make a student wait for a page.
  * Never break the app. If mail is not configured, or the server refuses, the
    in-app notification is already saved and the failure is logged and dropped.
  * Never mail someone who said no. Each account carries a switch.

Supabase is not involved. Its email service only handles auth mail —
confirmations, magic links, password resets — and has no API for sending
arbitrary messages.

Two ways out, chosen by MAIL_TRANSPORT:

  * "resend" posts to the Resend HTTP API. Nothing to install: it is one
    HTTPS request made with the standard library. Needs RESEND_API_KEY and
    a MAIL_FROM on a domain verified with Resend.
  * "smtp" talks to any SMTP server — Gmail, Zoho, Brevo, your own domain.

Both are kept because they fail differently and a site that cannot send
should be able to switch without a code change. Everything above this line
is true of either: the message is built once, and only the last step differs.
"""
import html
import json
import logging
import smtplib
import ssl
import threading
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr

from flask import current_app

log = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"

#: Resend's own test sender. It works with no domain at all, which makes it
#: the obvious thing to put in MAIL_FROM while getting started — and it
#: delivers only to the address the Resend account was opened with. Every
#: other recipient comes back 403. Left undetected that means a site that
#: appears configured, passes its own test email, and silently fails to send
#: a single student anything.
RESEND_TEST_DOMAIN = "resend.dev"


def sender_is_test_only(app=None):
    """Whether MAIL_FROM can only reach the account holder.

    True when sending over Resend from an address on resend.dev.
    """
    cfg = (app or current_app).config
    if transport(app) != "resend":
        return False
    sender = (cfg.get("MAIL_FROM") or "").strip().lower()
    return sender.endswith("@" + RESEND_TEST_DOMAIN) or sender.endswith(
        "." + RESEND_TEST_DOMAIN)


def transport(app=None):
    """Which way mail leaves: "resend" or "smtp"."""
    cfg = (app or current_app).config
    name = (cfg.get("MAIL_TRANSPORT") or "").strip().lower()
    if name in ("resend", "smtp"):
        return name
    # Unset but a key is present: the person configuring this clearly meant
    # Resend, and making them set two variables to say one thing is a way to
    # have mail silently not send.
    return "resend" if cfg.get("RESEND_API_KEY") else "smtp"


def configured(app=None):
    """Whether mail can go out at all.

    What counts as configured depends on the transport: Resend needs a key
    and no host, SMTP needs a host and no key.
    """
    cfg = (app or current_app).config
    if not cfg.get("MAIL_ENABLED") or not cfg.get("MAIL_FROM"):
        return False
    if transport(app) == "resend":
        return bool(cfg.get("RESEND_API_KEY"))
    return bool(cfg.get("MAIL_HOST"))


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


def _parts(msg):
    """The plain and HTML bodies out of a built message."""
    text = markup = ""
    for part in msg.walk():
        kind = part.get_content_type()
        if kind == "text/plain" and not text:
            text = part.get_content()
        elif kind == "text/html" and not markup:
            markup = part.get_content()
    return text, markup


def _send_smtp(cfg, msg):
    """Hand the message to an SMTP server. Returns (sent, detail)."""
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
        return True, ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _send_resend(cfg, msg):
    """Post the message to the Resend API. Returns (sent, detail).

    One HTTPS request with the standard library rather than a dependency,
    because adding a package to send an HTTP POST is a lot of moving parts
    for a POST.

    Resend's own error body is passed back rather than swallowed: "domain
    not verified" and "invalid api key" are the two things that actually go
    wrong here, and both are unguessable from a bare False.
    """
    text, markup = _parts(msg)
    payload = {
        "from": msg["From"],
        "to": [msg["To"]],
        "subject": msg["Subject"],
    }
    if markup:
        payload["html"] = markup
    if text:
        payload["text"] = text
    if msg["Reply-To"]:
        payload["reply_to"] = msg["Reply-To"]

    request = urllib.request.Request(
        RESEND_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {cfg['RESEND_API_KEY']}",
                 "Content-Type": "application/json"},
        method="POST")

    try:
        with urllib.request.urlopen(
                request, timeout=cfg.get("MAIL_TIMEOUT", 20)) as response:
            body = response.read().decode("utf-8", "replace")
        log.info("resend accepted mail to %s (%s)", msg["To"], body[:120])
        return True, ""
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        try:                                   # Resend answers with JSON
            detail = json.loads(detail).get("message", detail)
        except Exception:
            pass
        # The commonest failure by far, and the least self-explanatory:
        # sending from resend.dev to anybody but the account holder. Say
        # what it actually means rather than passing on the API's wording.
        if exc.code == 403 and RESEND_TEST_DOMAIN in str(cfg.get("MAIL_FROM", "")):
            return False, (
                f"Resend refused it (403). You are sending from "
                f"{cfg['MAIL_FROM']}, which is Resend's test address — it "
                f"only delivers to the email you opened your Resend account "
                f"with. To reach anybody else you need your own domain "
                f"verified on resend.com, and MAIL_FROM set to an address on "
                f"it. Until then use SMTP for real mail.")
        return False, f"Resend refused it ({exc.code}): {detail}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _send(cfg, msg, how=None):
    """Deliver by whichever transport is configured. Returns (sent, detail)."""
    how = how or ("resend" if cfg.get("MAIL_TRANSPORT", "").lower() == "resend"
                  or (not cfg.get("MAIL_TRANSPORT") and cfg.get("RESEND_API_KEY"))
                  else "smtp")
    if how == "resend":
        return _send_resend(cfg, msg)
    return _send_smtp(cfg, msg)


def _deliver(cfg, msg):
    """Fire-and-forget delivery, for the background thread."""
    sent, detail = _send(cfg, msg)
    if sent:
        log.info("mail sent to %s", msg["To"])
    else:
        # The in-app alert is already saved, so a mail failure costs nothing
        # but the email itself. Log it and carry on.
        log.warning("mail to %s failed: %s", msg["To"], detail)
    return sent


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
    how = transport(app)
    if not app.config.get("MAIL_ENABLED"):
        return False, "Email is switched off for this site (MAIL_ENABLED)."
    if not app.config.get("MAIL_FROM"):
        return False, "No sending address is configured (MAIL_FROM)."
    if how == "resend" and not app.config.get("RESEND_API_KEY"):
        return False, "No Resend API key is configured (RESEND_API_KEY)."
    if how == "smtp" and not app.config.get("MAIL_HOST"):
        return False, "No mail server is configured (MAIL_HOST)."
    if not to_address:
        return False, "This account has no email address."

    # Deliberately the same delivery code every other message goes through.
    # A test button with its own copy of the sending logic can pass while
    # real mail fails, which makes it worse than no button.
    msg = _build(app.config, to_address, to_name, subject, body, url)
    sent, detail = _send(app.config, msg, how)
    if not sent:
        log.warning("test mail to %s failed: %s", to_address, detail)
    return sent, detail


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
        "it is accepted. Every project you finish goes on your Praxfolio with "
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
            f"{brand}.\n\n"
            f"{brand} is where companies post work they actually need doing, "
            f"students take it on in teams, a lecturer reviews it before it "
            f"ships, and every finished project leaves a record an employer "
            f"can check.\n\n"
            f"The link below opens the invitation. Have a look at what the "
            f"place is first — nothing is asked of you until you decide. If "
            f"you want in, one button creates your account and puts you on "
            f"{from_name}'s team. It is free for students and there is "
            f"nothing to pay, ever.")

    return send(to_address, None, f"{from_name} invited you to a team on {brand}",
                body, f"/invite/{token}", app=app)


def send_team_invite_member(app, to_address, to_name, from_name, team_name):
    """Ask someone who already has an account to join a team.

    Deliberately not the same message as send_team_invite. That one is written
    for a stranger and spends its words explaining what the platform is and
    telling them to register; sent to a member it reads as nonsense and the
    link goes to a signup page they cannot use. This one assumes they are
    already here and points at the one thing they have to do: decide.
    """
    if not configured(app):
        return False

    brand = app.config["BRAND"]
    body = (f"{from_name} has invited you to join the team \"{team_name}\" on "
            f"{brand}.\n\n"
            f"A team applies for a brief as one unit, and every member gets "
            f"their own placement and their own certificate for the work.\n\n"
            f"You are already signed up, so there is nothing to create. Open "
            f"your Teams page to accept or decline — until you do, the team "
            f"is holding a seat for you.")

    return send(to_address, to_name,
                f"{from_name} invited you to the team \"{team_name}\" - {brand}",
                body, "/teams", app=app)


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
