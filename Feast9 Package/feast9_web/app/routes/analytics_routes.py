import json
from datetime import date

from flask import Blueprint, render_template, request

from app import db
from app.auth import login_required

bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@bp.route("/")
@login_required
def analytics_home():
    try:
        year = int(request.args.get("year", date.today().year))
    except (ValueError, TypeError):
        year = date.today().year

    data = db.get_analytics_data(year)
    return render_template(
        "analytics.html",
        data=data,
        year=year,
        data_json=json.dumps(data),
    )
