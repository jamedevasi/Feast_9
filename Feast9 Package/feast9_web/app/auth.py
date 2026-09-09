"""
Authentication for the single-practitioner login.

Uses Werkzeug's password hashing (no extra dependency) and Flask's signed
session cookie to track the logged-in user. On first run, with no users in
the database, every request is redirected to /setup to create the one
admin account.
"""
from functools import wraps
from flask import session, redirect, url_for, request, flash
from werkzeug.security import generate_password_hash, check_password_hash

from app import db


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def normalize_answer(answer: str) -> str:
    """Security-question answers are matched case/whitespace-insensitively
    so a practitioner isn't locked out by "Kochi" vs "kochi " typos."""
    return (answer or "").strip().lower()


def get_client_ip() -> str:
    """Best-effort client IP for rate limiting. Prefers X-Forwarded-For
    (set by virtually every reverse proxy / cloud host) since
    request.remote_addr would otherwise just be the proxy's own address."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return db.get_user_by_id(uid)


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not db.has_any_user():
            return redirect(url_for("auth.setup"))
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapped
