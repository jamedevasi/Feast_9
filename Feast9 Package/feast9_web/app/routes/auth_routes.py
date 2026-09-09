from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from app import db
from app.auth import hash_password, verify_password, normalize_answer, get_client_ip
from app.constants import SECURITY_QUESTIONS

bp = Blueprint("auth", __name__)

RATE_LIMIT_MESSAGE = (
    "Too many attempts from this connection. Please wait 15 minutes and try again."
)


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if db.has_any_user():
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        question_choice = request.form.get("security_question", "")
        question_custom = request.form.get("security_question_custom", "").strip()
        answer = request.form.get("security_answer", "").strip()

        security_question = question_custom if question_choice.startswith("Other") else question_choice

        errors = []
        if not username:
            errors.append("Username is required.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if not security_question:
            errors.append("Please choose or write a security question.")
        if not answer:
            errors.append("Please provide an answer to your security question.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("setup.html", username=username,
                                    security_questions=SECURITY_QUESTIONS)
        db.create_user(username, hash_password(password), security_question,
                        hash_password(normalize_answer(answer)))
        flash("Admin account created. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("setup.html", username="", security_questions=SECURITY_QUESTIONS)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not db.has_any_user():
        return redirect(url_for("auth.setup"))
    if request.method == "POST":
        ip = get_client_ip()
        if db.is_rate_limited(ip, "login"):
            flash(RATE_LIMIT_MESSAGE, "danger")
            return render_template("login.html")

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.get_user_by_username(username)
        success = bool(user and verify_password(password, user["password_hash"]))
        db.record_login_attempt(ip, "login", success)

        if success:
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session.permanent = True
            nxt = request.args.get("next") or url_for("dashboard.home")
            return redirect(nxt)
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# Password recovery — security-question based (no email server required).
# Two-stage form: enter username -> answer the security question + set a
# new password. If no question was ever set up for that account, the
# practitioner is pointed at the reset_admin_password.py CLI fallback.
# Rate limited the same way as login, since the "answer" stage is
# otherwise brute-forceable just like a password.
# ---------------------------------------------------------------------------
@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("forgot_password.html", stage="username")

    ip = get_client_ip()
    if db.is_rate_limited(ip, "forgot_password"):
        flash(RATE_LIMIT_MESSAGE, "danger")
        return render_template("forgot_password.html", stage="username")

    stage = request.form.get("stage", "username")

    if stage == "username":
        username = request.form.get("username", "").strip()
        user = db.get_user_by_username(username)
        if not user or not user.get("security_question"):
            flash("No recovery question is set up for that account. Ask whoever "
                  "manages your server to run the reset_admin_password.py script "
                  "included with the app — it resets the password directly.", "danger")
            return render_template("forgot_password.html", stage="username")
        return render_template("forgot_password.html", stage="answer", username=username,
                                security_question=user["security_question"])

    # stage == "answer"
    username = request.form.get("username", "").strip()
    answer = request.form.get("answer", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    user = db.get_user_by_username(username)
    if not user or not user.get("security_question"):
        flash("Something went wrong — please start again.", "danger")
        return redirect(url_for("auth.forgot_password"))

    answer_correct = verify_password(normalize_answer(answer), user["security_answer_hash"])
    db.record_login_attempt(ip, "forgot_password", answer_correct)

    errors = []
    if not answer_correct:
        errors.append("That answer doesn't match our records.")
    if len(new_password) < 6:
        errors.append("New password must be at least 6 characters.")
    if new_password != confirm_password:
        errors.append("New passwords do not match.")
    if errors:
        for e in errors:
            flash(e, "danger")
        return render_template("forgot_password.html", stage="answer", username=username,
                                security_question=user["security_question"])

    db.update_user_password(user["id"], hash_password(new_password))
    flash("Password reset successfully — please log in.", "success")
    return redirect(url_for("auth.login"))
