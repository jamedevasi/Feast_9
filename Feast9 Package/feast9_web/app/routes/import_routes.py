import io
import os
import uuid

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, send_file, abort
)

from app import excel_import
from app.auth import login_required
from app.config import UPLOADS_DIR

bp = Blueprint("import_data", __name__, url_prefix="/import")

ALLOWED_EXT = (".xlsx",)


@bp.route("/")
@login_required
def import_home():
    return render_template("import.html")


@bp.route("/template")
@login_required
def download_template():
    data = excel_import.build_template_xlsx()
    return send_file(
        io.BytesIO(data),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name="feast9_historic_patients_template.xlsx",
    )


@bp.route("/preview", methods=["POST"])
@login_required
def preview():
    file = request.files.get("file")
    if not file or file.filename == "":
        flash("Please choose an .xlsx file to upload.", "danger")
        return redirect(url_for("import_data.import_home"))
    if not file.filename.lower().endswith(ALLOWED_EXT):
        flash("Only .xlsx files are supported.", "danger")
        return redirect(url_for("import_data.import_home"))

    token = uuid.uuid4().hex
    save_path = os.path.join(UPLOADS_DIR, f"{token}.xlsx")
    file.save(save_path)

    try:
        with open(save_path, "rb") as f:
            result = excel_import.preview_import(f.read())
    except Exception as e:
        os.remove(save_path)
        flash(f"Could not read that file: {e}", "danger")
        return redirect(url_for("import_data.import_home"))

    if result.get("error"):
        os.remove(save_path)
        flash(result["error"], "danger")
        return redirect(url_for("import_data.import_home"))

    return render_template("import_preview.html", result=result, token=token,
                            filename=file.filename)


@bp.route("/confirm", methods=["POST"])
@login_required
def confirm():
    token = request.form.get("token", "")
    safe_token = "".join(c for c in token if c.isalnum())
    save_path = os.path.join(UPLOADS_DIR, f"{safe_token}.xlsx")
    if not safe_token or not os.path.exists(save_path):
        flash("Your import session expired — please upload the file again.", "danger")
        return redirect(url_for("import_data.import_home"))

    with open(save_path, "rb") as f:
        result = excel_import.preview_import(f.read())
    inserted = excel_import.commit_import(result["valid_rows"])
    os.remove(save_path)
    flash(f"Imported {inserted} patient record(s) successfully.", "success")
    return redirect(url_for("patients.list_patients"))


@bp.route("/cancel", methods=["POST"])
@login_required
def cancel():
    token = request.form.get("token", "")
    safe_token = "".join(c for c in token if c.isalnum())
    save_path = os.path.join(UPLOADS_DIR, f"{safe_token}.xlsx")
    if safe_token and os.path.exists(save_path):
        os.remove(save_path)
    flash("Import cancelled — no records were added.", "success")
    return redirect(url_for("import_data.import_home"))
