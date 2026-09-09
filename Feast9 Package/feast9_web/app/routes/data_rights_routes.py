"""
DPDP Phase 2 — Data Principal Rights (Sections 11-14, DPDP Act 2023).

Routes for:
  • Listing all pending / historical data requests
  • Raising a new request against a patient (Access, Correction, Erasure,
    Withdraw Consent) — typically initiated by the doctor on behalf of the
    patient who asked in person or by phone
  • Actioning / resolving a request with a resolution note
  • Generating the Right to Access PDF (all data held on a patient)
  • Executing soft-erasure (Right to Erasure)
"""
import io
import os
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, send_file, abort,
)

from app import db, pdf_reports, branding
from app.auth import login_required
from app.validators import clean_str

bp = Blueprint("data_rights", __name__, url_prefix="/data-rights")


@bp.route("/")
@login_required
def list_requests():
    status_filter = request.args.get("status", "")
    requests_list = db.list_data_requests(status=status_filter or None)
    pending_count = db.count_pending_data_requests()
    from datetime import date
    return render_template("data_rights_list.html", requests=requests_list,
                            status_filter=status_filter, pending_count=pending_count,
                            statuses=db.DATA_REQUEST_STATUSES,
                            today_str=date.today().isoformat())


@bp.route("/new/<int:patient_id>", methods=["GET", "POST"])
@login_required
def new_request(patient_id):
    patient = db.get_patient(patient_id)
    if not patient:
        abort(404)
    if request.method == "POST":
        req_type    = request.form.get("request_type", "")
        description = clean_str(request.form.get("description"))
        if req_type not in db.DATA_REQUEST_TYPES:
            flash("Please select a valid request type.", "danger")
            return render_template("data_rights_new.html", patient=patient,
                                    request_types=db.DATA_REQUEST_TYPES), 400
        rid = db.add_data_request(patient_id, req_type, description)
        flash(f"'{req_type}' request logged. 90-day response window started.", "success")
        return redirect(url_for("data_rights.view_request", request_id=rid))
    return render_template("data_rights_new.html", patient=patient,
                            request_types=db.DATA_REQUEST_TYPES)


@bp.route("/<int:request_id>", methods=["GET", "POST"])
@login_required
def view_request(request_id):
    req = db.get_data_request(request_id)
    if not req:
        abort(404)
    patient = db.get_patient(req["patient_id"])
    if request.method == "POST":
        action = request.form.get("action", "")
        resolution_note = clean_str(request.form.get("resolution_note"))

        if action == "complete":
            db.update_data_request(request_id, "Completed", resolution_note)
            flash("Request marked as Completed.", "success")

        elif action == "reject":
            if not resolution_note:
                flash("Please provide a reason for rejecting this request.", "danger")
                return redirect(url_for("data_rights.view_request", request_id=request_id))
            db.update_data_request(request_id, "Rejected", resolution_note)
            flash("Request marked as Rejected with reason recorded.", "success")

        elif action == "in_progress":
            db.update_data_request(request_id, "In Progress", resolution_note)
            flash("Request status updated to In Progress.", "success")

        elif action == "erasure_execute":
            # Execute soft anonymisation — irreversible
            confirm = request.form.get("erasure_confirm", "")
            if confirm != patient["name"]:
                flash("Confirmation name didn't match. Type the patient's exact "
                      "name to confirm erasure.", "danger")
                return redirect(url_for("data_rights.view_request", request_id=request_id))
            db.anonymise_patient(patient["id"])
            db.update_data_request(
                request_id, "Completed",
                "Patient data anonymised. Clinical/financial records retained "
                "per 7-year statutory retention obligation."
            )
            flash("Patient personal data has been anonymised. Clinical records "
                  "retained as required by law.", "success")
            return redirect(url_for("data_rights.list_requests"))

        elif action == "withdraw_consent":
            db.update_comms_consent(patient["id"], False)
            db.update_data_request(
                request_id, "Completed",
                "Communications consent withdrawn and revoked in the system."
            )
            flash("Communications consent withdrawn and logged.", "success")

        return redirect(url_for("data_rights.view_request", request_id=request_id))

    # Reload after any POST redirect
    req = db.get_data_request(request_id)
    return render_template("data_rights_view.html", req=req, patient=patient,
                            statuses=db.DATA_REQUEST_STATUSES)


@bp.route("/<int:request_id>/access-pdf")
@login_required
def access_pdf(request_id):
    """Generates the comprehensive data export PDF for a Right to Access request."""
    req = db.get_data_request(request_id)
    if not req or req["request_type"] != "Access":
        abort(404)
    patient = db.get_patient(req["patient_id"])
    cases   = db.list_cases_for_patient(patient["id"])
    for c in cases:
        c["doctor_name"] = db.case_doctor_name(c)
    payments_by_case     = {c["id"]: db.list_payments_for_case(c["id"]) for c in cases}
    prescriptions_by_case= {c["id"]: db.list_prescriptions_for_case(c["id"]) for c in cases}
    consents_by_case     = {c["id"]: db.list_consents_for_case(c["id"]) for c in cases}
    appointments         = db.list_appointments_for_patient(patient["id"])
    clinic               = db.get_all_settings()

    pdf_bytes = pdf_reports.generate_data_access_pdf(
        patient, cases, payments_by_case, prescriptions_by_case,
        consents_by_case, appointments, clinic, branding.get_logo_path()
    )
    # Mark the request as In Progress once the export is generated
    if req["status"] == "Pending":
        db.update_data_request(request_id, "In Progress",
                                "Data export generated and ready for delivery.")
    filename = f"data_export_{patient['name'].replace(' ','_')}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                      as_attachment=False, download_name=filename)
