"""
Lightweight CSRF protection — no new dependency, just a per-session random
token that every state-changing form must echo back.

Why this matters: without it, a malicious page the practitioner happens to
have open in another tab could silently submit a form to this app (e.g.
"delete patient") using their already-logged-in session cookie, and the
app would have no way to tell that request apart from a real one.
"""
import secrets
from flask import session, request, abort

CSRF_SESSION_KEY = "_csrf_token"
CSRF_FORM_FIELD = "csrf_token"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def get_csrf_token() -> str:
    """Returns the current session's CSRF token, creating one if needed.
    Safe to call from a GET request before any login — Flask's session
    cookie exists (signed, empty) from the very first response."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_hex(24)
        session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf():
    """Call from a before_request hook. Aborts the request with 400 if a
    state-changing request doesn't carry a valid, matching token."""
    if request.method in SAFE_METHODS:
        return
    # Static files and the logo route are GET-only anyway, but be explicit:
    if request.endpoint in ("branding.logo_image", "static"):
        return
    expected = session.get(CSRF_SESSION_KEY)
    submitted = request.form.get(CSRF_FORM_FIELD)
    if not expected or not submitted or not secrets.compare_digest(expected, submitted):
        abort(400, description="Your session expired or the form was submitted from a "
                                "stale page. Please go back, refresh, and try again.")
