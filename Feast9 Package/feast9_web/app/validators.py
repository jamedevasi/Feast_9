"""Small, dependency-free validators used by forms and the Excel importer."""
import re
from datetime import datetime

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y", "%d %B %Y")


def clean_str(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def is_valid_mobile(value: str) -> bool:
    value = clean_str(value)
    digits = re.sub(r"\D", "", value)
    return 7 <= len(digits) <= 15


def is_valid_email(value: str) -> bool:
    value = clean_str(value)
    if value == "":
        return True  # optional
    return bool(EMAIL_RE.match(value))


def normalize_date(value) -> str:
    """Return ISO 'YYYY-MM-DD' string from many possible input formats.
    Returns '' if value is empty, raises ValueError if unparseable."""
    if value is None or value == "":
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    value = clean_str(value)
    if value == "":
        return ""
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {value!r}")


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def now_iso() -> str:
    """Full date+time, second precision — used where minute-level recency
    matters (e.g. login rate limiting), unlike today_iso() which is
    date-only."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_valid_age(value) -> bool:
    if value is None or value == "":
        return True
    try:
        n = int(value)
        return 0 <= n <= 130
    except (ValueError, TypeError):
        return False


def validate_patient(name: str, mobile: str, email: str, age) -> list:
    """Return list of error strings (empty list = valid)."""
    errors = []
    if clean_str(name) == "":
        errors.append("Name is required.")
    if clean_str(mobile) == "":
        errors.append("Mobile number is required.")
    elif not is_valid_mobile(mobile):
        errors.append("Mobile number looks invalid (need 7-15 digits).")
    if not is_valid_email(email):
        errors.append("Email address looks invalid.")
    if not is_valid_age(age):
        errors.append("Age must be a whole number between 0 and 130.")
    return errors
