"""
Branding — lets the practitioner swap in their own clinic logo from
Settings instead of being stuck with the bundled placeholder.

A custom logo, once uploaded, is normalized to PNG and stored under
DATA_DIR (the same persistent volume used for the database) rather than
inside the app's static folder — that folder may be read-only or get
wiped on redeploy depending on hosting setup, whereas DATA_DIR is always
the designated persistent location.
"""
import os
import io

from PIL import Image, UnidentifiedImageError

from app.config import DATA_DIR, BASE_DIR

BRANDING_DIR = os.path.join(DATA_DIR, "branding")
CUSTOM_LOGO_PATH = os.path.join(BRANDING_DIR, "logo.png")
DEFAULT_LOGO_PATH = os.path.join(BASE_DIR, "app", "static", "img", "logo.png")

MAX_DIMENSION = 800          # px — plenty for both screen and PDF use
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB raw upload cap, before resizing

os.makedirs(BRANDING_DIR, exist_ok=True)


def has_custom_logo() -> bool:
    return os.path.exists(CUSTOM_LOGO_PATH)


def get_logo_path() -> str:
    """Returns the path PDF generation and the /branding/logo route should
    read from — the custom upload if one exists, else the bundled default."""
    return CUSTOM_LOGO_PATH if has_custom_logo() else DEFAULT_LOGO_PATH


def save_uploaded_logo(file_storage) -> None:
    """Validates, normalizes (downsizes + converts to PNG), and saves an
    uploaded logo. Raises ValueError with a user-facing message on any
    problem, so the route can just flash(str(e))."""
    if file_storage is None or file_storage.filename == "":
        raise ValueError("Please choose an image file to upload.")

    raw = file_storage.read()
    if len(raw) == 0:
        raise ValueError("That file appears to be empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("That image is too large (limit 5 MB) — please use a smaller file.")

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()  # force full decode now, so corrupt files fail here, not later
    except UnidentifiedImageError:
        raise ValueError("That doesn't look like a valid image file (PNG/JPG supported).")
    except Exception:
        raise ValueError("Could not read that image — please try a different file.")

    # Normalize to RGBA on a square-ish canvas isn't required — just cap
    # the largest dimension and convert to PNG so every downstream consumer
    # (nav bar, login screen, PDFs) gets a consistent, reasonably-sized file.
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    w, h = img.size
    if max(w, h) > MAX_DIMENSION:
        scale = MAX_DIMENSION / max(w, h)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

    os.makedirs(BRANDING_DIR, exist_ok=True)
    img.save(CUSTOM_LOGO_PATH, format="PNG")


def remove_custom_logo() -> bool:
    """Deletes the custom logo, reverting to the bundled default. Returns
    True if a file was actually removed."""
    if has_custom_logo():
        os.remove(CUSTOM_LOGO_PATH)
        return True
    return False
