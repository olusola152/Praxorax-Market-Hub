"""Send one email to yourself to check the settings work.

    python send_test_email.py you@example.com

Prints exactly what went wrong if it fails, instead of failing silently the
way a background send does.
"""
import sys
import logging

from app import app
import mailer

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1

    address = sys.argv[1]
    cfg = app.config

    print(f"MAIL_ENABLED  {cfg['MAIL_ENABLED']}")
    print(f"MAIL_HOST     {cfg['MAIL_HOST']}:{cfg['MAIL_PORT']}")
    print(f"MAIL_FROM     {cfg['MAIL_FROM']}")
    print(f"STARTTLS      {cfg['MAIL_STARTTLS']}   SSL {cfg['MAIL_SSL']}")
    print(f"BASE_URL      {cfg['BASE_URL']}\n")

    if not mailer.configured(app):
        print("Not configured. MAIL_ENABLED must be true, and MAIL_HOST and "
              "MAIL_FROM must both be set in .env.")
        return 1

    app.config["MAIL_SYNCHRONOUS"] = True
    with app.app_context():
        ok = mailer.send(
            address, "",
            f"Test message - {cfg['BRAND']}",
            "If you are reading this, email is working. Nothing is wrong; "
            "someone ran the test script.",
            "/")

    if ok:
        print(f"Sent to {address}. Check the inbox, and the spam folder.")
        return 0

    print("\nFailed. The log line above gives the reason. Common causes:")
    print("  535 auth failed   Gmail needs an App Password, not your login")
    print("  Connection refused / timeout   wrong host or port, or a firewall")
    print("  SSL errors        port 465 needs MAIL_SSL=true and STARTTLS=false")
    return 1


if __name__ == "__main__":
    sys.exit(main())
