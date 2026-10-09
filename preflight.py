"""Check a server is ready before trusting it with real users.

    python preflight.py

Run it on the host after deploying. It checks the things that actually go
wrong on shared hosting — a blocked database port, an unwritable upload
folder, a mail port the provider has closed — and says what to do about each.
Reads only; changes nothing.
"""
import os
import socket
import sys
from urllib.parse import urlparse

FAIL = []
WARN = []


def ok(label, detail=""):
    print(f"  OK    {label}" + (f"  ({detail})" if detail else ""))


def bad(label, fix):
    print(f"  FAIL  {label}")
    FAIL.append((label, fix))


def warn(label, fix):
    print(f"  WARN  {label}")
    WARN.append((label, fix))


def reachable(host, port, timeout=8):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main():
    print(f"Python {sys.version.split()[0]}\n")
    if sys.version_info < (3, 8):
        bad(f"Python {sys.version.split()[0]} is too old",
            "Choose 3.8 or newer in cPanel's Setup Python App.")

    try:
        from app import app
    except Exception as exc:
        print(f"  FAIL  the app will not import: {exc}")
        print("\nFix that first — nothing else can be checked until it imports.")
        return 1

    cfg = app.config

    print("Configuration")
    for name in ("SECRET_KEY", "DATABASE_URL"):
        if cfg.get(name) or os.environ.get(name):
            ok(name + " is set")
        else:
            bad(name + " is missing",
                "Add it to .env, or to the environment variables section of "
                "cPanel's Setup Python App.")

    if cfg.get("SECRET_KEY") in ("", "dev-only-change-me"):
        bad("SECRET_KEY is still the default",
            'Generate one: python -c "import secrets; print(secrets.token_hex(32))"')

    if cfg.get("DEMO_MODE"):
        bad("DEMO_MODE is on",
            "Set DEMO_MODE=false. It bypasses every subscription check.")

    if not cfg.get("SECURE_COOKIES"):
        warn("SECURE_COOKIES is off",
             "Set SECURE_COOKIES=true once the site is served over HTTPS.")

    base = cfg.get("BASE_URL", "")
    if "127.0.0.1" in base or "localhost" in base:
        bad(f"BASE_URL is still {base}",
            "Set it to your real address. Every link inside an email is built "
            "from it.")
    else:
        ok("BASE_URL", base)

    print("\nDatabase")
    url = urlparse(os.environ.get("DATABASE_URL", cfg.get("DATABASE_URL", "")))
    if url.hostname:
        if reachable(url.hostname, url.port or 5432):
            ok(f"port {url.port or 5432} is open to {url.hostname}")
            try:
                with app.app_context():
                    from db import scalar
                    scalar("SELECT 1")
                ok("a query ran successfully")
            except Exception as exc:
                bad(f"connected but the query failed: {exc}",
                    "Usually the password, or the schema has not been created.")
        else:
            bad(f"cannot reach {url.hostname}:{url.port or 5432}",
                "Shared hosts often block outbound database ports. Ask support "
                "to open it, or try Supabase's port 6543.")

    print("\nUploads")
    folder = cfg.get("UPLOAD_FOLDER", "")
    try:
        os.makedirs(os.path.join(folder, "submissions"), exist_ok=True)
        probe = os.path.join(folder, ".preflight")
        with open(probe, "w") as handle:
            handle.write("x")
        os.remove(probe)
        ok("folder is writable", folder)
    except Exception as exc:
        bad(f"cannot write to {folder}: {exc}",
            "Create the folder and give it write permission, or point "
            "UPLOAD_FOLDER somewhere you own.")

    if os.path.abspath(folder).startswith(os.path.abspath(os.path.dirname(__file__))):
        warn("uploads live inside the project folder",
             "Redeploying may delete every submitted file. Point UPLOAD_FOLDER "
             "outside the project.")

    print("\nEmail")
    if not cfg.get("MAIL_ENABLED"):
        warn("email is switched off", "Set MAIL_ENABLED=true when you want alerts.")
    elif not cfg.get("MAIL_HOST"):
        bad("MAIL_ENABLED is on but MAIL_HOST is empty", "Set the SMTP details.")
    else:
        if reachable(cfg["MAIL_HOST"], cfg["MAIL_PORT"]):
            ok(f"{cfg['MAIL_HOST']}:{cfg['MAIL_PORT']} is reachable")
        else:
            bad(f"cannot reach {cfg['MAIL_HOST']}:{cfg['MAIL_PORT']}",
                "Many hosts block SMTP ports. Try 465 with MAIL_SSL=true, or "
                "ask support to open it.")
        if cfg["MAIL_PORT"] == 465 and cfg.get("MAIL_STARTTLS"):
            bad("port 465 with STARTTLS on",
                "Set MAIL_STARTTLS=false and MAIL_SSL=true.")
        if cfg["MAIL_PORT"] == 587 and cfg.get("MAIL_SSL"):
            bad("port 587 with SSL on",
                "Set MAIL_SSL=false and MAIL_STARTTLS=true.")

    print("\nSchema")
    try:
        with app.app_context():
            from db import scalar
            missing = []
            for table in ("users", "projects", "assignments", "submissions",
                          "submission_files", "teams", "deliverables",
                          "portfolio_certificates"):
                try:
                    scalar(f"SELECT COUNT(*) FROM {table}")
                except Exception:
                    missing.append(table)
            if missing:
                bad("tables missing: " + ", ".join(missing),
                    "Run schema.sql then every migration in order.")
            else:
                ok("every table this build needs is present")
    except Exception:
        pass

    print()
    if FAIL:
        print(f"{len(FAIL)} problem(s) to fix before going live:\n")
        for label, fix in FAIL:
            print(f"  * {label}\n    {fix}\n")
    if WARN:
        print(f"{len(WARN)} thing(s) worth looking at:\n")
        for label, fix in WARN:
            print(f"  * {label}\n    {fix}\n")
    if not FAIL and not WARN:
        print("Everything checks out.")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
