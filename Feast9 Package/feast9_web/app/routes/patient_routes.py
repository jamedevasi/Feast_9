from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, send_file, abort
)
import io, os

from app import db, pdf_reports, branding
from app.auth import login_required
from app.validators import validate_patient, normalize_date, is_valid_mobile, now_iso
from app.constants import SEX_OPTIONS, MEDICAL_CONDITIONS, ALLERGY_DRUGS, DPDP_NOTICE_TEXT
from app.config import BASE_DIR

bp = Blueprint("patients", __name__, url_prefix="/patients")


@bp.route("/")
@login_required
def list_patients():
    search = request.args.get("q", "").strip()
    page = max(int(request.args.get("page", 1) or 1), 1)
    result = db.list_patients(search=search, page=page, page_size=50)
    for p in result["patients"]:
        p["active_cases"] = db.patient_active_case_count(p["id"])
        p["outstanding"]  = db.patient_outstanding_balance(p["id"])
    ids = [p["id"] for p in result["patients"]]
    followup_status = db.get_patients_followup_status(ids)
    return render_template("patients_list.html", result=result, search=search, followup_status=followup_status)


def _render_form(patient=None, errors=[]):
    return render_template(
        "patient_form.html", patient=patient, sex_options=SEX_OPTIONS,
        medical_conditions_options=MEDICAL_CONDITIONS, allergy_options=ALLERGY_DRUGS,
        dpdp_notice=DPDP_NOTICE_TEXT, errors=errors,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_patient():
    if request.method == "POST":
        return _save_patient(None)
    return _render_form()


@bp.route("/<int:patient_id>/edit", methods=["GET", "POST"])
@login_required
def edit_patient(patient_id):
    patient = db.get_patient(patient_id)
    if not patient:
        abort(404)
    if request.method == "POST":
        return _save_patient(patient_id)
    return _render_form(patient)


def _collect_form():
    f = request.form
    age_raw = f.get("age", "").strip()
    return dict(
        name=f.get("name",""), age=age_raw, sex=f.get("sex",""),
        mobile=f.get("mobile",""), email=f.get("email",""),
        address=f.get("address",""), last_visited_date=f.get("last_visited_date",""),
        medical_conditions=f.getlist("medical_conditions"),
        medical_conditions_other=f.get("medical_conditions_other","").strip(),
        is_pregnant=1 if f.get("is_pregnant") else 0,
        is_nursing=1 if f.get("is_nursing") else 0,
        allergies=f.getlist("allergies"),
        allergies_other=f.get("allergies_other","").strip(),
        emergency_contact_name=f.get("emergency_contact_name","").strip(),
        emergency_contact_relation=f.get("emergency_contact_relation","").strip(),
        emergency_contact_number=f.get("emergency_contact_number","").strip(),
        dpdp_notice_accepted=1 if f.get("dpdp_notice_accepted") else 0,
        comms_consent=1 if f.get("comms_consent") else 0,
        guardian_name=f.get("guardian_name","").strip(),
        guardian_relation=f.get("guardian_relation","").strip(),
        guardian_mobile=f.get("guardian_mobile","").strip(),
    )


def _save_patient(patient_id):
    d = _collect_form()
    errors = validate_patient(d["name"], d["mobile"], d["email"], d["age"] or None)
    last_visited_date = ""
    try:
        last_visited_date = normalize_date(d["last_visited_date"])
    except ValueError:
        errors.append("Last visited date is not a valid date.")
    if d["emergency_contact_number"] and not is_valid_mobile(d["emergency_contact_number"]):
        errors.append("Emergency contact number looks invalid.")
    age_val = int(d["age"]) if d["age"] else None
    is_minor = bool(age_val and age_val < 18)
    if not patient_id and not d["dpdp_notice_accepted"]:
        errors.append("Please acknowledge the Data Processing Notice before registering.")
    if is_minor and not d["guardian_name"]:
        errors.append("Guardian name is required for patients under 18 (DPDP Act, Section 9).")
    if is_minor and d["guardian_mobile"] and not is_valid_mobile(d["guardian_mobile"]):
        errors.append("Guardian mobile number looks invalid.")
    if errors:
        for e in errors:
            flash(e, "danger")
        form_state = {**d, "id": patient_id}
        return _render_form(form_state, errors), 400

    ts = now_iso()
    kw = dict(
        medical_conditions=d["medical_conditions"],
        medical_conditions_other=d["medical_conditions_other"],
        is_pregnant=d["is_pregnant"], is_nursing=d["is_nursing"],
        allergies=d["allergies"], allergies_other=d["allergies_other"],
        emergency_contact_name=d["emergency_contact_name"],
        emergency_contact_relation=d["emergency_contact_relation"],
        emergency_contact_number=d["emergency_contact_number"],
        comms_consent=d["comms_consent"],
        comms_consent_at=ts if d["comms_consent"] else "",
        guardian_name=d["guardian_name"],
        guardian_relation=d["guardian_relation"],
        guardian_mobile=d["guardian_mobile"],
    )
    if patient_id:
        db.update_patient(patient_id, d["name"], age_val, d["sex"], d["mobile"],
                           d["email"], d["address"], last_visited_date,
                           dpdp_notice_accepted=d["dpdp_notice_accepted"] or None,
                           dpdp_notice_accepted_at=ts if d["dpdp_notice_accepted"] else None,
                           **kw)
        flash("Patient details updated.", "success")
        return redirect(url_for("patients.patient_detail", patient_id=patient_id))
    else:
        new_id = db.add_patient(d["name"], age_val, d["sex"], d["mobile"],
                                 d["email"], d["address"], last_visited_date,
                                 dpdp_notice_accepted=d["dpdp_notice_accepted"],
                                 dpdp_notice_accepted_at=ts if d["dpdp_notice_accepted"] else "",
                                 **kw)
        flash("Patient added.", "success")
        return redirect(url_for("patients.patient_detail", patient_id=new_id))


@bp.route("/<int:patient_id>")
@login_required
def patient_detail(patient_id):
    patient = db.get_patient(patient_id)
    if not patient:
        abort(404)
    cases = db.list_cases_for_patient(patient_id)
    for c in cases:
        c["doctor_name"] = db.case_doctor_name(c)
    doctors = db.list_doctors(active_only=True)
    appointments = db.list_appointments_for_patient(patient_id)
    from datetime import date
    return render_template("patient_detail.html", patient=patient, cases=cases,
                            doctors=doctors, appointments=appointments,
                            today_str=date.today().isoformat())


@bp.route("/<int:patient_id>/delete", methods=["POST"])
@login_required
def delete_patient(patient_id):
    patient = db.get_patient(patient_id)
    if not patient:
        abort(404)
    db.delete_patient(patient_id)
    flash(f"Deleted patient '{patient['name']}' and all their case records.", "success")
    return redirect(url_for("patients.list_patients"))


@bp.route("/<int:patient_id>/print")
@login_required
def print_patient_summary(patient_id):
    patient = db.get_patient(patient_id)
    if not patient:
        abort(404)
    cases = db.list_cases_for_patient(patient_id)
    for c in cases:
        c["doctor_name"] = db.case_doctor_name(c)
    clinic = db.get_all_settings()
    logo_path = branding.get_logo_path()
    pdf_bytes = pdf_reports.generate_patient_summary_pdf(patient, cases, clinic, logo_path)
    filename = f"patient_summary_{patient['name'].replace(' ','_')}_{patient_id}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                      as_attachment=False, download_name=filename)
