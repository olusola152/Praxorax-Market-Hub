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
    <p style="margin:0 0 24px;font-size:16px;line-height:1.55">{html.escape(body)}</p>
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


def subject_for(body, brand):
    """A subject line from the alert text, cut at the first sentence."""
    first = body.split(". ")[0].strip().rstrip(".")
    if len(first) > 72:
        first = first[:69].rsplit(" ", 1)[0] + "…"
    return f"{first} - {brand}"


# --------------------------------------------------------------- welcome

WELCOME = {
    "student": (
        "Your account is ready. Browse the open briefs, apply to anything that "
        "fits what you can do, and send your work through the site. Companies "
        "review it and sign it off, and every finished project goes on your "
        "portfolio with a certificate you can show an employer. Nothing to pay."),
    "company": (
        "Your account is ready and your free trial has started. Post a brief "
        "and universities will bring their students to it. Before a brief can "
        "go live we verify your company — send your registration document from "
        "the Verification page and an administrator will look at it."),
    "university": (
        "Your institution is set up and your free trial has started. Issue "
        "passcodes so your lecturers can join, and they will take on company "
        "briefs and place your students on them. Every submission passes "
        "through you before it reaches the company."),
    "lecturer": (
        "You are registered with your institution. Browse the open briefs, "
        "request any that suit your field, and once the company approves you "
        "can place your own students on it and review what they send."),
    "admin": "Your administrator account is ready.",
}


def send_welcome(app, to_address, to_name, role):
    """One message when an account is created, saying what to do next.

    Not a notification — there is no in-app equivalent and nothing to link to
    beyond the dashboard — so it is sent directly rather than through notify().
    """
    body = WELCOME.get(role)
    if not body or not configured(app):
        return False
    brand = app.config["BRAND"]
    return send(to_address, to_name, f"Welcome to {brand}", body, "/", app=app)
