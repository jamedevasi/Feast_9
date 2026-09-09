from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from app import db
from app.auth import login_required

bp = Blueprint("doctors", __name__, url_prefix="/doctors")


@bp.route("/", methods=["GET", "POST"])
@login_required
def list_doctors():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Doctor name is required.", "danger")
        else:
            try:
                db.add_doctor(name)
                flash(f"Doctor '{name}' added.", "success")
            except Exception:
                flash(f"A doctor named '{name}' already exists.", "danger")
        return redirect(url_for("doctors.list_doctors"))
    doctors = db.list_doctors(active_only=False)
    for d in doctors:
        d["in_use"] = db.doctor_in_use(d["id"])
    return render_template("doctors.html", doctors=doctors)


@bp.route("/<int:doctor_id>/edit", methods=["POST"])
@login_required
def edit_doctor(doctor_id):
    doctor = db.get_doctor(doctor_id)
    if not doctor:
        abort(404)
    name = request.form.get("name", "").strip()
    color = request.form.get("color", "").strip()
    if not name:
        flash("Doctor name cannot be empty.", "danger")
    else:
        db.update_doctor(doctor_id, name, color or None)
        flash("Doctor details updated.", "success")
    return redirect(url_for("doctors.list_doctors"))


@bp.route("/<int:doctor_id>/toggle", methods=["POST"])
@login_required
def toggle_doctor(doctor_id):
    doctor = db.get_doctor(doctor_id)
    if not doctor:
        abort(404)
    db.set_doctor_active(doctor_id, not doctor["active"])
    flash(f"Doctor '{doctor['name']}' is now {'active' if not doctor['active'] else 'inactive'}.",
          "success")
    return redirect(url_for("doctors.list_doctors"))
