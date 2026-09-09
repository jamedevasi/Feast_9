"""Feast9 — Flask application factory."""
import sys
from flask import Flask, render_template

from app.config import Config
from app import db as db_module
from app import backup as backup_module
from app.auth import current_user
from app.csrf import get_csrf_token, validate_csrf


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    if app.config["SECRET_KEY"] == "dev-only-change-me-in-production":
        print("\n*** WARNING: SECRET_KEY is still the default placeholder. ***\n"
              "*** Set a real SECRET_KEY environment variable before exposing ***\n"
              "*** this app to the internet — see .env.example.              ***\n",
              file=sys.stderr)

    db_module.init_db()
    backup_module.maybe_run_daily_backup()

    from app.routes.auth_routes import bp as auth_bp
    from app.routes.dashboard_routes import bp as dashboard_bp
    from app.routes.patient_routes import bp as patient_bp
    from app.routes.case_routes import bp as case_bp
    from app.routes.doctor_routes import bp as doctor_bp
    from app.routes.procedure_type_routes import bp as proc_bp
    from app.routes.report_routes import bp as report_bp
    from app.routes.import_routes import bp as import_bp
    from app.routes.settings_routes import bp as settings_bp
    from app.routes.appointment_routes import bp as appointment_bp
    from app.routes.branding_routes import bp as branding_bp
    from app.routes.data_rights_routes import bp as data_rights_bp
    from app.routes.analytics_routes import bp as analytics_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(case_bp)
    app.register_blueprint(doctor_bp)
    app.register_blueprint(proc_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(import_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(appointment_bp)
    app.register_blueprint(branding_bp)
    app.register_blueprint(data_rights_bp)
    app.register_blueprint(analytics_bp)

    @app.before_request
    def _csrf_check():
        validate_csrf()

    @app.after_request
    def _security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "frame-ancestors 'none'"
        )
        return response

    @app.context_processor
    def inject_globals():
        return {
            "clinic_name": db_module.get_setting("clinic_name", "Feast9"),
            "current_user": current_user(),
            "csrf_token": get_csrf_token,
            "pending_data_requests": db_module.count_pending_data_requests(),
        }

    @app.errorhandler(400)
    def bad_request(e):
        message = getattr(e, "description", None) or "Bad request."
        return render_template("error.html", code=400, message=message), 400

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="Page not found."), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template("error.html", code=413,
                                message="Uploaded file is too large (limit 25 MB)."), 413

    return app
