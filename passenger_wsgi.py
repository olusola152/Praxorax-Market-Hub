"""Entry point for cPanel hosting (WhoGoHost / GO54, and any Passenger host).

cPanel's "Setup Python App" runs your code under Phusion Passenger rather than
gunicorn, and it looks for a WSGI callable — by convention named `application`.

Point the cPanel form at THIS file, not app.py:

    Application startup file   passenger_wsgi.py
    Application entry point    application

That matters: cPanel overwrites the startup file with its own hello-world when
you first create the application. Letting it overwrite this stub costs nothing;
letting it overwrite app.py would destroy the app.
"""
import os
import sys

# Passenger does not always start in the project directory.
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from app import app as application  # noqa: E402

# Passenger imports this module and serves `application`. Nothing else runs.
