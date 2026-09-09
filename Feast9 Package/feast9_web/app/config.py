"""
Feast9 — configuration.

All paths are resolved relative to DATA_DIR, which defaults to ./instance
next to the app but can be overridden with the DATA_DIR environment
variable. On most cloud hosts you should point DATA_DIR at a persistent
disk/volume (see README.md) so the SQLite database and generated PDFs
survive deploys and restarts.
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "instance"))
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "feast9.db")

EXPORTS_DIR = os.path.join(DATA_DIR, "exports")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")
CONSENTS_DIR = os.path.join(DATA_DIR, "uploads", "consents")
for _d in (EXPORTS_DIR, UPLOADS_DIR, BACKUPS_DIR, CONSENTS_DIR):
    os.makedirs(_d, exist_ok=True)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB upload cap (historic xlsx imports)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set SESSION_COOKIE_SECURE=1 once your deployment is served over HTTPS
    # (true for virtually every cloud host) — see README.md.
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # 12 hours


# Brand colors — kept in one place so CSS and server-rendered PDFs match.
class Brand:
    NAME = "Feast9"
    PRIMARY_DARK = "#2E7D32"
    PRIMARY = "#43A047"
    PRIMARY_LIGHT = "#8BC34A"
    ACCENT = "#C8E6C9"
    BG = "#F4FBF4"
    DANGER = "#C62828"
    WARNING = "#F9A825"
    BORDER = "#CFE3D0"
