import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("SAMAY_DB", BACKEND_DIR / "data" / "samay.db"))
# Set SAMAY_COOKIE_SECURE=1 when serving over HTTPS so the sign-in cookie is never sent over plain HTTP.
COOKIE_SECURE = os.environ.get("SAMAY_COOKIE_SECURE", "0") == "1"
ALLOWED_ORIGINS = [o for o in os.environ.get("SAMAY_ORIGINS", "http://localhost:5173,http://localhost:5500").split(",") if o]
