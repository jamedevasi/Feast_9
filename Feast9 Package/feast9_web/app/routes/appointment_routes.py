import calendar as calmod
from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify

from app import db
from app.auth import login_required
from app.validators import normalize_date, clean_str

bp = Blueprint("appointments", __name__, url_prefix="/appointments")

WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _build_month_matrix(year: int, month: int):
    """Returns a list of weeks (Sun-first); each day is a dict with date,
    iso string, in_month flag, is_today flag, and its appointments."""
    cal = calmod.Calendar(firstweekday=6)  # week starts Sunday
    first_of_month = date(year, month, 1)
    today = date.today()

    start_iso = first_of_month.isoformat()
    last_day = calmod.monthrange(year, month)[1]
    end_iso = date(year, month, last_day).isoformat()
    appts = db.list_appointments_for_range(start_iso, end_iso)
    by_day = {}
    for a in appts:
        by_day.setdefault(a["appt_date"], []).append(a)

    weeks = []
    week = []
    for d in cal.itermonthdates(year, month):
        iso = d.isoformat()
        week.append({
            "date": d,
            "iso": iso,
            "in_month": d.month == month,
            "is_today": d == today,
            "appointments": sorted(by_day.get(iso, []), key=lambda a: a["start_time"]),
        })
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        weeks.append(week)
    return weeks


def _prev_next(year, month):
    first = date(year, month, 1)
    prev_month = first - timedelta(days=1)
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (prev_month.year, prev_month.month), (next_month.year, next_month.month)


@bp.route("/")
@login_required
def calendar_view():
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        date(year, month, 1)  # validate
    except (ValueError, TypeError):
        year, month = today.year, today.month

    weeks = _build_month_matrix(year, month)
    (py, pm), (ny, nm) = _prev_next(year, month)
    doctors = db.list_doctors(active_only=True)
    month_name = date(year, month, 1).strftime("%B %Y")

    return render_template(
        "calendar_month.html", weeks=weeks, weekday_labels=WEEKDAY_LABELS,
        year=year, month=month, month_name=month_name,
        prev_year=py, prev_month=pm, next_year=ny, next_month=nm,
        doctors=doctors, today_iso=today.isoformat(),
    )


@bp.route("/day/<day>")
@login_required
def day_view(day):
    try:
        normalize_date(day)
    except ValueError:
        abort(404)
    appts = db.list_appointments_for_day(day)
    day_obj = datetime.strptime(day, "%Y-%m-%d").date()
    return render_template("calendar_day.html", day=day, day_obj=day_obj, appointments=appts)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_appointment():
    if request.method == "POST":
        return _save_appointment(None)
    prefill_date = request.args.get("date", date.today().isoformat())
    prefill_patient_id = request.args.get("patient_id", "")
    doctors = db.list_doctors(active_only=True)
    prefill_patient = db.get_patient(int(prefill_patient_id)) if prefill_patient_id else None
    return render_template(
        "appointment_form.html", appt=None, doctors=doctors,
        statuses=db.APPOINTMENT_STATUSES, prefill_date=prefill_date,
        prefill_patient=prefill_patient, errors=[],
    )


@bp.route("/<int:appt_id>/edit", methods=["GET", "POST"])
@login_required
def edit_appointment(appt_id):
    appt = db.get_appointment(appt_id)
    if not appt:
        abort(404)
    if request.method == "POST":
        return _save_appointment(appt_id)
    doctors = db.list_doctors(active_only=True)
    prefill_patient = db.get_patient(appt["patient_id"])
    return render_template(
        "appointment_form.html", appt=appt, doctors=doctors,
        statuses=db.APPOINTMENT_STATUSES, prefill_date=appt["appt_date"],
        prefill_patient=prefill_patient, errors=[],
    )


def _save_appointment(appt_id):
    patient_id = request.form.get("patient_id", "").strip()
    doctor_id = request.form.get("doctor_id") or None
    appt_date_raw = request.form.get("appt_date", "")
    start_time = request.form.get("start_time", "").strip()
    end_time = request.form.get("end_time", "").strip()
    title = clean_str(request.form.get("title"))
    notes = clean_str(request.form.get("notes"))
    status = request.form.get("status", "Scheduled")

    errors = []
    patient = None
    if not patient_id:
        errors.append("Please select a patient (search by name or mobile).")
    else:
        try:
            patient = db.get_patient(int(patient_id))
        except (ValueError, TypeError):
            patient = None
        if not patient:
            errors.append("Selected patient could not be found — please search and pick again.")
    try:
        appt_date = normalize_date(appt_date_raw)
        if not appt_date:
            errors.append("Appointment date is required.")
    except ValueError:
        errors.append("Appointment date is not a valid date.")
        appt_date = ""
    if not start_time:
        errors.append("Start time is required.")
    if end_time and start_time and end_time <= start_time:
        errors.append("End time must be after the start time.")

    if errors:
        for e in errors:
            flash(e, "danger")
        doctors = db.list_doctors(active_only=True)
        form_state = {
            "id": appt_id, "patient_id": patient_id, "doctor_id": int(doctor_id) if doctor_id else None,
            "appt_date": appt_date_raw, "start_time": start_time, "end_time": end_time,
            "title": title, "notes": notes, "status": status,
        }
        return render_template(
            "appointment_form.html", appt=form_state, doctors=doctors,
            statuses=db.APPOINTMENT_STATUSES, prefill_date=appt_date_raw,
            prefill_patient=patient, errors=errors,
        ), 400

    doctor_id_val = int(doctor_id) if doctor_id else None
    if appt_id:
        db.update_appointment(appt_id, patient["id"], doctor_id_val, appt_date, start_time,
                               end_time, title, notes, status)
        flash("Appointment updated.", "success")
    else:
        appt_id = db.add_appointment(patient["id"], doctor_id_val, appt_date, start_time,
                                      end_time, title, notes, status)
        flash("Appointment scheduled.", "success")
    y, m = appt_date[:4], appt_date[5:7]
    return redirect(url_for("appointments.calendar_view", year=int(y), month=int(m)))


@bp.route("/<int:appt_id>/delete", methods=["POST"])
@login_required
def delete_appointment(appt_id):
    appt = db.get_appointment(appt_id)
    if not appt:
        abort(404)
    appt_date = appt["appt_date"]
    db.delete_appointment(appt_id)
    flash("Appointment cancelled and removed.", "success")
    y, m = appt_date[:4], appt_date[5:7]
    return redirect(url_for("appointments.calendar_view", year=int(y), month=int(m)))


@bp.route("/<int:appt_id>/status", methods=["POST"])
@login_required
def quick_status(appt_id):
    appt = db.get_appointment(appt_id)
    if not appt:
        abort(404)
    status = request.form.get("status", "Scheduled")
    if status not in db.APPOINTMENT_STATUSES:
        abort(400)
    db.set_appointment_status(appt_id, status)
    flash(f"Marked as {status}.", "success")
    return redirect(request.referrer or url_for("appointments.calendar_view"))


@bp.route("/search-patients")
@login_required
def search_patients():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    results = db.search_patients_basic(q, limit=10)
    return jsonify(results)
