import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))


def _flag(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")


class Config:
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    SECRET_KEY = os.environ.get("SECRET_KEY", "")

    # A blank UPLOAD_FOLDER= line in .env must fall back, not become an empty
    # path — os.environ.get returns "" for a blank value, not the default.
    UPLOAD_FOLDER = (os.environ.get("UPLOAD_FOLDER") or "").strip() \
        or os.path.join(BASE_DIR, "uploads")
    # Whole request ceiling. Per-file and per-submission limits live in
    # storage.py, which gives a clearer message than a bare 413.
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set SECURE_COOKIES=true once the site is behind HTTPS. Leave it off for
    # local development or the session cookie is never sent back.
    SESSION_COOKIE_SECURE = _flag("SECURE_COOKIES")
    PREFERRED_URL_SCHEME = "https" if _flag("SECURE_COOKIES") else "http"

    # DEMO MODE — opens registration and treats every subscription as active,
    # so the whole flow can be walked through before any money changes hands.
    # A banner appears on every page while it is on. Never enable in production.
    DEMO_MODE = _flag("DEMO_MODE")

    # Independent students sign up on the main page with no university behind
    # them. They never sit under an institutional subscription, so their work
    # is supervised by the company directly. Turn this off to go back to
    # institutions-only signup.
    OPEN_STUDENT_SIGNUP = _flag("OPEN_STUDENT_SIGNUP", True)

    # A university or company that signs up gets this many days free, with no
    # payment and no admin step. Set to 0 to switch trials off; existing
    # trials then simply run out on their own dates.
    TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "7"))

    # The product name. Everything user-facing reads this, so renaming is a
    # one-line change rather than a hunt through templates.
    BRAND = os.environ.get("BRAND", "PraxoraX")

    # Absolute address of this site. Links inside emails are built from it, so
    # set it to your real domain in production or every message will point at
    # localhost.
    BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:5000").rstrip("/")

    # ------------------------------------------------------- presentations
    # Presentation times are typed and read in this timezone. The database
    # stores UTC; only the display and the parsing use this. Set it to where
    # the institution actually is, or everyone books an hour off.
    TIMEZONE = os.environ.get("TIMEZONE", "Africa/Lagos")

    # The video server that hosts a defence. meet.jit.si needs no account and
    # no API key, which is why it is the default — but it is a public service
    # that rate-limits embedded use, so point this at your own Jitsi install
    # before a client depends on it. Anyone who prefers Zoom or Meet pastes a
    # link instead and none of the rest of this changes.
    JITSI_DOMAIN = os.environ.get("JITSI_DOMAIN", "meet.jit.si")

    # How far ahead a session must be booked. Fifteen minutes stops anyone
    # confirming a meeting that is already starting, which is right in
    # production and a nuisance while demonstrating the flow in one sitting —
    # set it to 0 to book a session for a minute from now, then put it back.
    MIN_NOTICE_MINUTES = max(int(os.environ.get("MIN_NOTICE_MINUTES", "15")), 0)

    # ------------------------------------------------------------ email
    # Alerts also go out by email when this is on and a host is set.
    # Supabase cannot send these — its email service only covers auth mail
    # (confirmations, magic links, password resets) — so this talks to an
    # SMTP server directly. Any provider works.
    MAIL_ENABLED = _flag("MAIL_ENABLED")
    MAIL_HOST = os.environ.get("MAIL_HOST", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USER = os.environ.get("MAIL_USER", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", "")
    MAIL_REPLY_TO = os.environ.get("MAIL_REPLY_TO", "")
    MAIL_STARTTLS = _flag("MAIL_STARTTLS", True)
    MAIL_SSL = _flag("MAIL_SSL")            # port 465 style
    MAIL_TIMEOUT = int(os.environ.get("MAIL_TIMEOUT", "20"))
    MAIL_SYNCHRONOUS = _flag("MAIL_SYNCHRONOUS")   # tests only

    # How many failed sign-ins from one address before it is made to wait.
    LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", 8))
    LOGIN_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", 300))
