import os

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file

from app import db, branding, backup
from app.auth import login_required, hash_password, verify_password, normalize_answer, current_user
from app.constants import SECURITY_QUESTIONS

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/", methods=["GET", "POST"])
@login_required
def view_settings():
    if request.method == "POST":
        form = request.form.get("form")

        if form == "clinic":
            db.set_setting("clinic_name", request.form.get("clinic_name", "Feast9").strip())
            db.set_setting("clinic_address", request.form.get("clinic_address", "").strip())
            db.set_setting("clinic_phone", request.form.get("clinic_phone", "").strip())
            db.set_setting("clinic_email", request.form.get("clinic_email", "").strip())
            flash("Clinic details updated.", "success")

        elif form == "password":
            user = current_user()
            old_pw = request.form.get("old_password", "")
            new_pw = request.form.get("new_password", "")
            confirm_pw = request.form.get("confirm_password", "")
            if not verify_password(old_pw, user["password_hash"]):
                flash("Current password is incorrect.", "danger")
            elif len(new_pw) < 6:
                flash("New password must be at least 6 characters.", "danger")
            elif new_pw != confirm_pw:
                flash("New passwords do not match.", "danger")
            else:
                db.update_user_password(user["id"], hash_password(new_pw))
                flash("Password changed.", "success")

        elif form == "security":
            user = current_user()
            current_pw = request.form.get("current_password_for_security", "")
            question_choice = request.form.get("security_question", "")
            question_custom = request.form.get("security_question_custom", "").strip()
            answer = request.form.get("security_answer", "").strip()
            security_question = question_custom if question_choice.startswith("Other") else question_choice

            if not verify_password(current_pw, user["password_hash"]):
                flash("Current password is incorrect.", "danger")
            elif not security_question:
                flash("Please choose or write a security question.", "danger")
            elif not answer:
                flash("Please provide an answer.", "danger")
            else:
                db.update_security_question(user["id"], security_question,
                                             hash_password(normalize_answer(answer)))
                flash("Security question updated.", "success")

        elif form == "logo":
            try:
                branding.save_uploaded_logo(request.files.get("logo_file"))
                flash("Logo updated.", "success")
            except ValueError as e:
                flash(str(e), "danger")

        elif form == "logo_remove":
            if branding.remove_custom_logo():
                flash("Custom logo removed — reverted to the default.", "success")
            else:
                flash("There's no custom logo to remove.", "warning")

        elif form == "backup_delete":
            filename = request.form.get("filename", "")
            if backup.delete_backup(filename):
                flash(f"Deleted backup {filename}.", "success")
            else:
                flash("Could not find that backup file.", "danger")

        return redirect(url_for("settings.view_settings"))

    clinic = db.get_all_settings()
    user = current_user()
    return render_template(
        "settings.html", clinic=clinic, user=user, security_questions=SECURITY_QUESTIONS,
        has_custom_logo=branding.has_custom_logo(), backups=backup.list_backups(),
    )


@bp.route("/backup/download")
@login_required
def download_backup():
    path = backup.create_backup(backup.MANUAL_PREFIX)
    filename = os.path.basename(path)
    return send_file(path, mimetype="application/octet-stream", as_attachment=True,
                      download_name=f"feast9_{filename}")


@bp.route("/backup/download/<filename>")
@login_required
def download_existing_backup(filename):
    path = backup.safe_backup_path(filename)
    if not path:
        flash("Could not find that backup file.", "danger")
        return redirect(url_for("settings.view_settings"))
    return send_file(path, mimetype="application/octet-stream", as_attachment=True,
                      download_name=f"feast9_{filename}")


@bp.route("/backup/excel")
@login_required
def download_excel_backup():
    """Generates and streams a human-readable Excel workbook of all patients
    and cases — the Plan B spreadsheet that works without the app."""
    from datetime import date
    try:
        xlsx_bytes = backup.generate_excel_backup()
    except Exception as e:
        flash(f"Could not generate Excel export: {e}", "danger")
        return redirect(url_for("settings.view_settings"))
    filename = f"feast9_export_{date.today().isoformat()}.xlsx"
    import io
    return send_file(
        io.BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )
