import os
from datetime import timedelta

from flask import Flask, g, jsonify, redirect, render_template, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from auth_utils import (ROLE_LABELS, dashboard_for, enforce_idle_timeout,
                        load_current_user, seconds_left)
from config import Config
from db import close_db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    if not app.config["SECRET_KEY"]:
        raise RuntimeError(
            "SECRET_KEY is not set. Generate one with "
            '`python -c "import secrets; print(secrets.token_hex(32))"` '
            "and put it in .env or the host's environment.")

    # Behind a load balancer the real client address and scheme arrive in
    # headers; without this, redirects and rate limiting see the proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Submitted project files live here.
    os.makedirs(os.path.join(app.config["UPLOAD_FOLDER"], "submissions"),
                exist_ok=True)

    app.teardown_appcontext(close_db)

    # Order matters. The idle check runs first and can end the request before
    # the user is ever loaded, so an expired session never reaches a view.
    app.before_request(enforce_idle_timeout)
    app.before_request(load_current_user)

    # The cookie itself expires too, so closing the browser for longer than
    # the timeout leaves nothing behind to resume.
    app.permanent_session_lifetime = timedelta(
        minutes=max(app.config["IDLE_TIMEOUT_MINUTES"], 1) + 5)

    @app.context_processor
    def inject_notifications():
        from workflow import subscription_live, unread_count
        if not g.get("user"):
            return {}
        uni = g.get("university")
        return {
            "unread": unread_count(g.user["id"]),
            "sub_live": (subscription_live(uni.get("subscription_status"),
                                           uni.get("subscribed_until"))
                         if uni else True),
        }

    from routes.admin import admin_bp
    from routes.auth import auth_bp
    from routes.company import company_bp
    from routes.contact import contact_bp
    from routes.deliverables import deliverables_bp
    from routes.files import files_bp
    from routes.messages import messages_bp
    from routes.invites import invites_bp
    from routes.praxfolio import praxfolio_bp
    from routes.presentations import presentations_bp
    from routes.settings import settings_bp
    from routes.teams import teams_bp
    from routes.lecturer import lecturer_bp
    from routes.portal import portal_bp
    from routes.student import student_bp
    from routes.university import university_bp

    for bp in (auth_bp, portal_bp, student_bp, lecturer_bp, university_bp,
               company_bp, admin_bp, files_bp, teams_bp, invites_bp,
               contact_bp, messages_bp,
               deliverables_bp, praxfolio_bp, presentations_bp, settings_bp):
        app.register_blueprint(bp)

    # Pictures on the public site, and the folder a real photograph is
    # dropped into to replace one. Read once, here, not per render.
    import artwork
    artwork.attach(app)

    def _share_to(network, link, title=""):
        """A share link for one network, for the Praxfolio page."""
        import social
        return social.share_url(network, link, title) or "#"

    def _platform_links():
        """PraxoraX's own social accounts, for the footers.

        A function rather than a value so the query runs on the handful of
        templates that show them, not on every render of every page.
        """
        import social
        try:
            return social.links_for(None)
        except Exception:
            # A footer must never be the thing that takes a page down.
            return []

    def _unread_messages():
        """Messages waiting, for the badge in the top bar.

        Only the two roles that can have a supervision thread pay for the
        query; everybody else gets zero without touching the database.

        Guarded, like the footer links, because this runs on every render
        for those two roles. Code reaches a server before a migration does
        — that is the normal order of a deploy — and when it did, a missing
        messages table took down every page a student could open rather
        than the one feature that needed it. A badge is worth none of that:
        if the count cannot be had, there is no badge.
        """
        user = g.get("user")
        if not user or user["role"] not in ("student", "lecturer"):
            return 0
        try:
            from routes.messages import unread_for
            return unread_for(user["id"])
        except Exception:
            app.logger.warning(
                "unread message count unavailable — has migration_v12 been run?",
                exc_info=True)
            return 0

    @app.context_processor
    def inject_labels():
        # trial_days is here so the public copy can offer a trial only when
        # one is actually on. A site that advertises a free week and then
        # hands out a pending account is worse than one that never mentioned it.
        from datetime import date
        return {"role_labels": ROLE_LABELS, "brand": app.config["BRAND"],
                "trial_days": app.config["TRIAL_DAYS"],
                "now_year": date.today().year,
                "idle_seconds_left": seconds_left(),
                "unread_messages": _unread_messages(),
                "platform_links": _platform_links,
                "share_to": _share_to,
                "idle_warn_at": app.config["IDLE_WARN_SECONDS"]}

    @app.context_processor
    def inject_next_session():
        """The soonest presentation, for the reminder on a dashboard.

        Handed over as a function rather than a value so the query only runs
        on the three templates that ask for it, not on every page render.
        """
        import presentations as pres

        def next_session():
            user = g.get("user")
            return pres.next_up(user["id"]) if user else None

        return {"next_session": next_session, "pres_helper": pres}

    @app.context_processor
    def inject_trial():
        """Days left on a free week, for the banner in base.html."""
        from workflow import trial_days_left
        user = g.get("user")
        left = None
        if user:
            if user["role"] == "company":
                left = trial_days_left(user.get("company_subscription"),
                                       user.get("company_until"))
            elif user["role"] in ("university", "lecturer", "student"):
                uni = g.get("university")
                if uni:
                    left = trial_days_left(uni["subscription_status"],
                                           uni["subscribed_until"])
        return {"trial_left": left}

    @app.context_processor
    def inject_mail():
        import mailer
        user = g.get("user")
        return {
            "mail_configured": mailer.configured(app),
            "user_email_alerts": bool(user and user.get("email_notifications", True)),
        }

    @app.route("/")
    def home():
        if g.get("user"):
            return redirect(dashboard_for(g.user["role"]))
        from db import query
        from workflow import expire_lapsed
        expire_lapsed()

        # There was a band of live counts here. On a platform this young it
        # read "3 briefs, 1 institution", which argues against the product
        # rather than for it, so it is gone along with the four queries that
        # fed it. Worth restoring once the real numbers carry themselves.
        return render_template(
            "public/landing.html",
            fields=query(
                """SELECT name, faculty, image_url FROM fields
                    WHERE image_url IS NOT NULL ORDER BY name LIMIT 8"""),
            universities=query(
                """SELECT name, slug, city FROM universities
                    WHERE subscription_status IN ('active','trial')
                    ORDER BY name LIMIT 12"""))

    @app.route("/healthz")
    def healthz():
        """Liveness probe for the host. Does not touch the database."""
        return jsonify(status="ok")

    @app.errorhandler(413)
    def too_large(_):
        return render_template("error.html", code=413,
                               message="That upload is too large."), 413

    @app.errorhandler(429)
    def too_many(_):
        return render_template("error.html", code=429,
                               message="Too many attempts. Try again shortly."), 429

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403,
                               message="You do not have access to that."), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404,
                               message="That page does not exist."), 404

    @app.errorhandler(410)
    def file_gone(_):
        return render_template(
            "error.html", code=410,
            message="That file is recorded but is no longer on the server.",
            detail="The upload folder has been emptied or moved since it was "
                   "sent. Ask whoever submitted it to upload it again. To stop "
                   "this happening, set UPLOAD_FOLDER in .env to a path outside "
                   "the project folder, so replacing the code cannot delete "
                   "the files."), 410

    @app.errorhandler(500)
    def server_error(_):
        return render_template("error.html", code=500,
                               message="Something broke on our side. Try again."), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
