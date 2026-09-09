from flask import Blueprint, render_template

from app import db
from app.auth import login_required

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def home():
    overdue, upcoming = db.get_followup_alerts()
    total_outstanding = db.get_total_outstanding()
    active_cases = db.get_active_case_count()
    closed_cases = db.get_closed_case_count()
    total_patients = db.count_patients()
    recent_cases = db.list_all_cases()[:8]
    for c in recent_cases:
        c["doctor_name"] = db.case_doctor_name(c)
    todays_appointments = db.list_todays_appointments()
    pending_rights = db.count_pending_data_requests()
    return render_template(
        "dashboard.html",
        overdue=overdue,
        upcoming=upcoming,
        total_outstanding=total_outstanding,
        active_cases=active_cases,
        closed_cases=closed_cases,
        total_patients=total_patients,
        recent_cases=recent_cases,
        todays_appointments=todays_appointments,
        pending_rights=pending_rights,
    )
