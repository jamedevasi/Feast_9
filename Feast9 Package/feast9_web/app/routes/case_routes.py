from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, send_file, abort
)
import io
import os
import re
import base64
import uuid

from PIL import Image as PILImage, UnidentifiedImageError

from app import db, pdf_reports, branding
from app.auth import login_required
from app.validators import normalize_date, clean_str
from app.constants import CASE_STATUS_OPTIONS, PAYMENT_METHODS, DEFAULT_CONSENT_TEXT
from app.config import CONSENTS_DIR

bp = Blueprint("cases", __name__)


def _logo_path():
    return branding.get_logo_path()


@bp.route("/patients/<int:patient_id>/cases/new", methods=["GET", "POST"])
@login_required
def new_case(patient_id):
    patient = db.get_patient(patient_id)
    if not patient:
        abort(404)
    if request.method == "POST":
        return _save_case(patient_id, None)
    doctors = db.list_doctors(active_only=True)
    procedure_types = db.list_procedure_types(active_only=True)
    return render_template(
        "case_form.html", patient=patient, case=None, doctors=doctors,
        procedure_types=procedure_types, status_options=CASE_STATUS_OPTIONS, errors=[],
    )


@bp.route("/cases/<int:case_id>/edit", methods=["GET", "POST"])
@login_required
def edit_case(case_id):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    patient = db.get_patient(case["patient_id"])
    if request.method == "POST":
        return _save_case(case["patient_id"], case_id)
    doctors = db.list_doctors(active_only=True)
    procedure_types = db.list_procedure_types(active_only=True)
    return render_template(
        "case_form.html", patient=patient, case=case, doctors=doctors,
        procedure_types=procedure_types, status_options=CASE_STATUS_OPTIONS, errors=[],
    )


def _save_case(patient_id, case_id):
    title = clean_str(request.form.get("title"))
    status = request.form.get("status", "Active")
    procedures = request.form.getlist("procedures")
    custom_procedure = clean_str(request.form.get("custom_procedure"))
    doctor_id = request.form.get("doctor_id") or None
    total_cost = request.form.get("total_cost", "0").strip()
    next_action_note = clean_str(request.form.get("next_action_note"))
    follow_up_raw = request.form.get("follow_up_date", "")

    errors = []
    if not title:
        errors.append("Case title is required.")
    try:
        total_cost_val = float(total_cost) if total_cost else 0.0
        if total_cost_val < 0:
            errors.append("Total cost cannot be negative.")
    except ValueError:
        errors.append("Total cost must be a number.")
        total_cost_val = 0.0
    try:
        follow_up_date = normalize_date(follow_up_raw)
    except ValueError:
        errors.append("Follow-up date is not a valid date.")
        follow_up_date = ""
    if not procedures and not custom_procedure:
        errors.append("Select at least one procedure or describe it in the custom field.")

    if errors:
        for e in errors:
            flash(e, "danger")
        patient = db.get_patient(patient_id)
        doctors = db.list_doctors(active_only=True)
        procedure_types = db.list_procedure_types(active_only=True)
        form_state = {
            "id": case_id, "title": title, "status": status, "procedures": procedures,
            "custom_procedure": custom_procedure, "doctor_id": int(doctor_id) if doctor_id else None,
            "total_cost": total_cost, "next_action_note": next_action_note,
            "follow_up_date": follow_up_raw,
        }
        return render_template(
            "case_form.html", patient=patient, case=form_state, doctors=doctors,
            procedure_types=procedure_types, status_options=CASE_STATUS_OPTIONS, errors=errors,
        ), 400

    doctor_id_val = int(doctor_id) if doctor_id else None
    if case_id:
        db.update_case(case_id, title, status, procedures, custom_procedure, doctor_id_val,
                        total_cost_val, next_action_note, follow_up_date)
        flash("Case updated.", "success")
    else:
        case_id = db.add_case(patient_id, title, status, procedures, custom_procedure,
                               doctor_id_val, total_cost_val, next_action_note, follow_up_date)
        flash("Case created.", "success")
        flash("⚠ Obtain patient consent before treatment starts — see the Consent Forms section.", "warning")
        return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="consents"))
    return redirect(url_for("cases.case_detail", case_id=case_id))


@bp.route("/cases/<int:case_id>")
@login_required
def case_detail(case_id):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    patient = db.get_patient(case["patient_id"])
    payments = db.list_payments_for_case(case_id)
    prescriptions = db.list_prescriptions_for_case(case_id)
    balance = db.get_case_balance(case_id)
    total_paid = db.get_case_total_paid(case_id)
    doctor_name = db.case_doctor_name(case)
    amendments = db.list_case_amendments(case_id)
    visit_notes = db.list_visit_notes(case_id)
    consents = db.list_consents_for_case(case_id)
    return render_template(
        "case_detail.html", case=case, patient=patient, payments=payments,
        prescriptions=prescriptions, balance=balance, total_paid=total_paid,
        doctor_name=doctor_name, payment_methods=PAYMENT_METHODS,
        amendments=amendments, visit_notes=visit_notes, consents=consents,
    )


@bp.route("/cases/<int:case_id>/delete", methods=["POST"])
@login_required
def delete_case(case_id):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    patient_id = case["patient_id"]
    db.delete_case(case_id)
    flash("Case deleted.", "success")
    return redirect(url_for("patients.patient_detail", patient_id=patient_id))


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@bp.route("/cases/<int:case_id>/payments/add", methods=["POST"])
@login_required
def add_payment(case_id):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    amount = request.form.get("amount", "").strip()
    payment_date_raw = request.form.get("payment_date", "")
    method = request.form.get("method", "")
    note = clean_str(request.form.get("note"))
    try:
        amount_val = float(amount)
        if amount_val <= 0:
            raise ValueError()
    except ValueError:
        flash("Payment amount must be a positive number.", "danger")
        return redirect(url_for("cases.case_detail", case_id=case_id))
    try:
        payment_date = normalize_date(payment_date_raw) or normalize_date(None)
    except ValueError:
        flash("Payment date is not valid.", "danger")
        return redirect(url_for("cases.case_detail", case_id=case_id))
    db.add_payment(case_id, amount_val, payment_date, method, note)
    flash("Payment recorded.", "success")
    return redirect(url_for("cases.case_detail", case_id=case_id))


@bp.route("/payments/<int:payment_id>/delete", methods=["POST"])
@login_required
def delete_payment(payment_id):
    payment = db.get_payment(payment_id)
    if not payment:
        abort(404)
    case_id = payment["case_id"]
    db.delete_payment(payment_id)
    flash("Payment entry removed.", "success")
    return redirect(url_for("cases.case_detail", case_id=case_id))


# ---------------------------------------------------------------------------
# Prescriptions
# ---------------------------------------------------------------------------
@bp.route("/cases/<int:case_id>/prescriptions/add", methods=["POST"])
@login_required
def add_prescription(case_id):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    rx_date_raw = request.form.get("rx_date", "")
    rx_details = clean_str(request.form.get("rx_details"))
    if not rx_details:
        flash("Prescription details cannot be empty.", "danger")
        return redirect(url_for("cases.case_detail", case_id=case_id))
    try:
        rx_date = normalize_date(rx_date_raw) or normalize_date(None)
    except ValueError:
        flash("Prescription date is not valid.", "danger")
        return redirect(url_for("cases.case_detail", case_id=case_id))
    rx_id = db.add_prescription(case_id, rx_date, rx_details)
    flash("Prescription added.", "success")
    return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="prescriptions"))


@bp.route("/prescriptions/<int:prescription_id>/delete", methods=["POST"])
@login_required
def delete_prescription(prescription_id):
    rx = db.get_prescription(prescription_id)
    if not rx:
        abort(404)
    case_id = rx["case_id"]
    db.delete_prescription(prescription_id)
    flash("Prescription removed.", "success")
    return redirect(url_for("cases.case_detail", case_id=case_id))


@bp.route("/prescriptions/<int:prescription_id>/print")
@login_required
def print_prescription(prescription_id):
    rx = db.get_prescription(prescription_id)
    if not rx:
        abort(404)
    case = db.get_case(rx["case_id"])
    patient = db.get_patient(case["patient_id"])
    doctor_name = db.case_doctor_name(case)
    clinic = db.get_all_settings()
    pdf_bytes = pdf_reports.generate_prescription_pdf(
        patient, case, rx, doctor_name, clinic, _logo_path()
    )
    filename = f"prescription_{patient['name'].replace(' ', '_')}_{rx['rx_date']}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                      as_attachment=False, download_name=filename)


# ---------------------------------------------------------------------------
# Case summary PDF (records / insurance)
# ---------------------------------------------------------------------------
@bp.route("/cases/<int:case_id>/print")
@login_required
def print_case_summary(case_id):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    purpose = request.args.get("purpose", "record")
    patient = db.get_patient(case["patient_id"])
    payments = db.list_payments_for_case(case_id)
    prescriptions = db.list_prescriptions_for_case(case_id)
    doctor_name = db.case_doctor_name(case)
    amendments = db.list_case_amendments(case_id)
    clinic = db.get_all_settings()
    pdf_bytes = pdf_reports.generate_case_summary_pdf(
        patient, case, payments, prescriptions, doctor_name, clinic, purpose,
        _logo_path(), amendments=amendments,
    )
    filename = f"case_summary_{patient['name'].replace(' ', '_')}_{case_id}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                      as_attachment=False, download_name=filename)


# ---------------------------------------------------------------------------
# Cost revisions — tracked changes to the case estimate mid-treatment
# ---------------------------------------------------------------------------
@bp.route("/cases/<int:case_id>/revise-cost", methods=["POST"])
@login_required
def revise_cost(case_id):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    new_cost_raw = request.form.get("new_total_cost", "").strip()
    reason = clean_str(request.form.get("reason"))
    amended_at_raw = request.form.get("amended_at", "")

    try:
        new_cost = float(new_cost_raw)
        if new_cost < 0:
            raise ValueError()
    except ValueError:
        flash("New estimate must be a valid, non-negative number.", "danger")
        return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="cost-history"))

    try:
        amended_at = normalize_date(amended_at_raw) or normalize_date(None)
    except ValueError:
        flash("Revision date is not valid.", "danger")
        return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="cost-history"))

    if not reason:
        flash("Please add a short reason for the revision (e.g. 'Surgical "
              "extraction identified after 2nd sitting') — it's kept as part "
              "of the case history.", "danger")
        return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="cost-history"))

    result = db.revise_case_cost(case_id, new_cost, reason, amended_at)
    if result is None:
        flash("That's the same as the current estimate — nothing to record.", "warning")
    else:
        flash(f"Estimate revised to ₹{new_cost:,.2f}. The balance has been recalculated.",
              "success")
    return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="cost-history"))


@bp.route("/case-amendments/<int:amendment_id>/delete", methods=["POST"])
@login_required
def delete_amendment(amendment_id):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT case_id FROM case_amendments WHERE id=?", (amendment_id,)
        ).fetchone()
    if not row:
        abort(404)
    case_id = row["case_id"]
    db.delete_case_amendment(amendment_id)
    flash("Amendment entry removed from the history (current cost unchanged).", "success")
    return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="cost-history"))


# ---------------------------------------------------------------------------
# Visit notes — update case details/progress at each subsequent visit
# ---------------------------------------------------------------------------
@bp.route("/cases/<int:case_id>/visit-notes/add", methods=["POST"])
@login_required
def add_visit_note(case_id):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    visit_date_raw = request.form.get("visit_date", "")
    note = clean_str(request.form.get("note"))
    if not note:
        flash("Visit note cannot be empty.", "danger")
        return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="visit-notes"))
    try:
        visit_date = normalize_date(visit_date_raw) or normalize_date(None)
    except ValueError:
        flash("Visit date is not valid.", "danger")
        return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="visit-notes"))
    db.add_visit_note(case_id, visit_date, note)
    flash("Visit note added.", "success")
    return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="visit-notes"))


@bp.route("/visit-notes/<int:note_id>/delete", methods=["POST"])
@login_required
def delete_visit_note(note_id):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT case_id FROM case_visit_notes WHERE id=?", (note_id,)
        ).fetchone()
    if not row:
        abort(404)
    case_id = row["case_id"]
    db.delete_visit_note(note_id)
    flash("Visit note removed.", "success")
    return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="visit-notes"))


# ---------------------------------------------------------------------------
# Consent forms
# ---------------------------------------------------------------------------
def _default_consent_text(patient, case, doctor_name):
    procedures = ", ".join(case.get("procedures") or []) or case.get("custom_procedure") or "the proposed treatment"
    return DEFAULT_CONSENT_TEXT.format(
        patient_name=patient["name"], doctor_name=doctor_name or "the treating doctor",
        case_title=case["title"], procedures=procedures,
    )


@bp.route("/cases/<int:case_id>/followup", methods=["POST"])
@login_required
def update_followup(case_id):
    case = db.get_case(case_id)
    if not case: abort(404)
    follow_up_date = request.form.get("follow_up_date", "").strip()
    next_action_note = clean_str(request.form.get("next_action_note", ""))
    try:
        follow_up_date = normalize_date(follow_up_date) if follow_up_date else ""
    except ValueError:
        follow_up_date = ""
    db.update_case_followup(case_id, follow_up_date, next_action_note)
    flash("Follow-up updated.", "success")
    return redirect(url_for("cases.case_detail", case_id=case_id))


@bp.route("/cases/<int:case_id>/consents/offline", methods=["POST"])
@login_required
def mark_consent_offline(case_id):
    case = db.get_case(case_id)
    if not case: abort(404)
    patient = db.get_patient(case["patient_id"])
    from app.constants import DEFAULT_CONSENT_TEXT
    doctor_name = db.case_doctor_name(case)
    procedures = ", ".join(case.get("procedures") or []) or case.get("custom_procedure") or "the proposed treatment"
    consent_text = DEFAULT_CONSENT_TEXT.format(
        patient_name=patient["name"], doctor_name=doctor_name or "the treating doctor",
        case_title=case["title"], procedures=procedures)
    try:
        signed_date = normalize_date(request.form.get("signed_date","")) or normalize_date(None)
    except ValueError:
        signed_date = normalize_date(None)
    notes = clean_str(request.form.get("offline_notes")) or "Consent collected on paper."
    db.add_consent(case_id, consent_text, signed_date,
                   db.SIGNATURE_TYPE_NONE, None, patient["name"], notes=notes)
    flash("Offline consent recorded. Keep the signed paper copy in the patient file.", "success")
    return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="consents"))


@bp.route("/cases/<int:case_id>/consents/new", methods=["GET", "POST"])
@login_required
def new_consent(case_id):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    patient = db.get_patient(case["patient_id"])
    doctor_name = db.case_doctor_name(case)

    if request.method == "GET":
        default_text = _default_consent_text(patient, case, doctor_name)
        return render_template("consent_form.html", case=case, patient=patient,
                                default_text=default_text, errors=[], form_state=None)

    consent_text = clean_str(request.form.get("consent_text"))
    signed_date_raw = request.form.get("signed_date", "")
    witness_name = clean_str(request.form.get("witness_name"))
    notes = clean_str(request.form.get("notes"))
    signature_mode = request.form.get("signature_mode", "drawn")
    drawn_data_url = request.form.get("drawn_signature", "")
    uploaded_file = request.files.get("signature_file")

    errors = []
    if not consent_text:
        errors.append("Consent text cannot be empty.")
    try:
        signed_date = normalize_date(signed_date_raw) or normalize_date(None)
    except ValueError:
        errors.append("Signed date is not valid.")
        signed_date = ""

    signature_type = None
    signature_filename = None

    if signature_mode == "drawn":
        if not drawn_data_url or "," not in drawn_data_url:
            errors.append("Please sign in the box before saving, or switch to "
                           "'Upload a signed copy' if signing isn't possible right now.")
        else:
            try:
                header, b64data = drawn_data_url.split(",", 1)
                raw = base64.b64decode(b64data)
                img = PILImage.open(io.BytesIO(raw))
                img.load()
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                # A signature pad left untouched still produces a fully
                # transparent/blank image — reject that as "didn't sign".
                if img.getbbox() is None:
                    errors.append("The signature box looks empty — please sign before saving.")
                else:
                    signature_type = db.SIGNATURE_TYPE_DRAWN
                    signature_filename = f"consent_{case_id}_{uuid.uuid4().hex}.png"
                    os.makedirs(CONSENTS_DIR, exist_ok=True)
                    img.save(os.path.join(CONSENTS_DIR, signature_filename), format="PNG")
            except Exception:
                errors.append("Could not read the signature — please try signing again.")
    else:  # uploaded
        if not uploaded_file or uploaded_file.filename == "":
            errors.append("Please choose a scanned/photographed signed copy to upload.")
        else:
            ext = os.path.splitext(uploaded_file.filename)[1].lower()
            if ext not in (".png", ".jpg", ".jpeg", ".pdf", ".webp"):
                errors.append("Please upload an image (PNG/JPG) or PDF of the signed form.")
            else:
                raw = uploaded_file.read()
                if len(raw) > 10 * 1024 * 1024:
                    errors.append("That file is too large (limit 10 MB).")
                else:
                    if ext == ".pdf":
                        if not raw.startswith(b"%PDF"):
                            errors.append("That doesn't look like a valid PDF file.")
                        else:
                            signature_type = db.SIGNATURE_TYPE_UPLOADED
                            signature_filename = f"consent_{case_id}_{uuid.uuid4().hex}.pdf"
                    else:
                        try:
                            img = PILImage.open(io.BytesIO(raw))
                            img.load()
                            signature_type = db.SIGNATURE_TYPE_UPLOADED
                            signature_filename = f"consent_{case_id}_{uuid.uuid4().hex}.png"
                            if img.mode != "RGB":
                                img = img.convert("RGB")
                            raw = None  # processed via img.save below
                        except UnidentifiedImageError:
                            errors.append("That doesn't look like a valid image file.")
                    if signature_filename and not errors:
                        os.makedirs(CONSENTS_DIR, exist_ok=True)
                        dest = os.path.join(CONSENTS_DIR, signature_filename)
                        if ext == ".pdf":
                            with open(dest, "wb") as f:
                                f.write(raw)
                        else:
                            img.save(dest, format="PNG")

    if errors:
        for e in errors:
            flash(e, "danger")
        form_state = {
            "consent_text": consent_text, "signed_date": signed_date_raw,
            "witness_name": witness_name, "notes": notes,
        }
        return render_template("consent_form.html", case=case, patient=patient,
                                default_text=consent_text, errors=errors,
                                form_state=form_state), 400

    db.add_consent(case_id, consent_text, signed_date, signature_type, signature_filename,
                    patient["name"], witness_name, notes)
    flash("Consent form saved.", "success")
    return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="consents"))


@bp.route("/cases/<int:case_id>/consents/blank-pdf")
@login_required
def blank_consent_pdf(case_id):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    patient = db.get_patient(case["patient_id"])
    doctor_name = db.case_doctor_name(case)
    clinic = db.get_all_settings()
    text = _default_consent_text(patient, case, doctor_name)
    pdf_bytes = pdf_reports.generate_consent_pdf(patient, case, {
        "consent_text": text, "signed_date": "", "witness_name": "",
    }, doctor_name, clinic, _logo_path(), signature_image_path=None, blank=True)
    filename = f"consent_form_blank_{patient['name'].replace(' ', '_')}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                      as_attachment=False, download_name=filename)


@bp.route("/consents/<int:consent_id>/print")
@login_required
def print_consent(consent_id):
    consent = db.get_consent(consent_id)
    if not consent:
        abort(404)
    case = db.get_case(consent["case_id"])
    patient = db.get_patient(case["patient_id"])
    doctor_name = db.case_doctor_name(case)
    clinic = db.get_all_settings()

    sig_path = None
    if consent["signature_filename"] and consent["signature_filename"].endswith(".png"):
        candidate = os.path.join(CONSENTS_DIR, consent["signature_filename"])
        if os.path.exists(candidate):
            sig_path = candidate

    pdf_bytes = pdf_reports.generate_consent_pdf(patient, case, consent, doctor_name, clinic,
                                                   _logo_path(), signature_image_path=sig_path)
    filename = f"consent_{patient['name'].replace(' ', '_')}_{consent['signed_date']}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                      as_attachment=False, download_name=filename)


@bp.route("/consents/<int:consent_id>/attachment")
@login_required
def consent_attachment(consent_id):
    consent = db.get_consent(consent_id)
    if not consent or not consent["signature_filename"]:
        abort(404)
    path = os.path.join(CONSENTS_DIR, consent["signature_filename"])
    safe_dir = os.path.abspath(CONSENTS_DIR)
    if os.path.abspath(path) != path or not path.startswith(safe_dir) or not os.path.exists(path):
        abort(404)
    mimetype = "application/pdf" if path.endswith(".pdf") else "image/png"
    return send_file(path, mimetype=mimetype)


@bp.route("/consents/<int:consent_id>/delete", methods=["POST"])
@login_required
def delete_consent(consent_id):
    consent = db.get_consent(consent_id)
    if not consent:
        abort(404)
    case_id = consent["case_id"]
    if consent["signature_filename"]:
        path = os.path.join(CONSENTS_DIR, consent["signature_filename"])
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    db.delete_consent(consent_id)
    flash("Consent record deleted.", "success")
    return redirect(url_for("cases.case_detail", case_id=case_id, _anchor="consents"))
