"""
Production WSGI entry point.

    gunicorn -w 2 -b 0.0.0.0:8000 wsgi:app

See README.md for full deployment instructions on Render, Railway, or a
generic Linux VPS.
"""
from app import create_app

app = create_app()
