from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from app import db
from app.auth import login_required

bp = Blueprint("procedure_types", __name__, url_prefix="/procedure-types")


@bp.route("/", methods=["GET", "POST"])
@login_required
def list_procedure_types():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Procedure name is required.", "danger")
        else:
            try:
                db.add_procedure_type(name)
                flash(f"Procedure type '{name}' added.", "success")
            except Exception:
                flash(f"A procedure type named '{name}' already exists.", "danger")
        return redirect(url_for("procedure_types.list_procedure_types"))
    procedure_types = db.list_procedure_types(active_only=False)
    return render_template("procedure_types.html", procedure_types=procedure_types)


@bp.route("/<int:pt_id>/edit", methods=["POST"])
@login_required
def edit_procedure_type(pt_id):
    name = request.form.get("name", "").strip()
    if not name:
        flash("Procedure name cannot be empty.", "danger")
    else:
        db.update_procedure_type(pt_id, name)
        flash("Procedure type updated.", "success")
    return redirect(url_for("procedure_types.list_procedure_types"))


@bp.route("/<int:pt_id>/toggle", methods=["POST"])
@login_required
def toggle_procedure_type(pt_id):
    pts = db.list_procedure_types(active_only=False)
    pt = next((p for p in pts if p["id"] == pt_id), None)
    if not pt:
        abort(404)
    db.set_procedure_type_active(pt_id, not pt["active"])
    flash(f"Procedure type '{pt['name']}' is now "
          f"{'active' if not pt['active'] else 'inactive'}.", "success")
    return redirect(url_for("procedure_types.list_procedure_types"))


@bp.route("/<int:pt_id>/delete", methods=["POST"])
@login_required
def delete_procedure_type(pt_id):
    db.delete_procedure_type(pt_id)
    flash("Procedure type deleted.", "success")
    return redirect(url_for("procedure_types.list_procedure_types"))
