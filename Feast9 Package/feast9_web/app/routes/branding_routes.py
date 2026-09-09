from flask import Blueprint, send_file

from app import branding

bp = Blueprint("branding", __name__, url_prefix="/branding")


@bp.route("/logo")
def logo_image():
    """Serves the current logo — no login required, since the login and
    setup screens themselves need to display it. Always returns PNG."""
    path = branding.get_logo_path()
    return send_file(path, mimetype="image/png", max_age=60)
