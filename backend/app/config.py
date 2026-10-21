import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = Path(os.environ.get("SAMAY_WEB_DIR", BACKEND_DIR.parent / "prototype"))  # the page served at "/"
DB_PATH = Path(os.environ.get("SAMAY_DB", BACKEND_DIR / "data" / "samay.db"))
# Set SAMAY_COOKIE_SECURE=1 when serving over HTTPS so the sign-in cookie is never sent over plain HTTP.
COOKIE_SECURE = os.environ.get("SAMAY_COOKIE_SECURE", "0") == "1"
# One-click sign-in for the seed demo accounts (no password). Turn off for a real launch: SAMAY_DEMO_LOGIN=0.
DEMO_LOGIN = os.environ.get("SAMAY_DEMO_LOGIN", "1") == "1"
SOLVE_SECONDS = float(os.environ.get("SAMAY_SOLVE_SECONDS", "30"))  # time limit for one generation run
ALLOWED_ORIGINS = [o for o in os.environ.get("SAMAY_ORIGINS", "http://localhost:5173,http://localhost:5500").split(",") if o]
