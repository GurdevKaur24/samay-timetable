import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = Path(os.environ.get("SAMAY_WEB_DIR", BACKEND_DIR.parent / "web"))  # the page served at "/"
DB_PATH = Path(os.environ.get("SAMAY_DB", BACKEND_DIR / "data" / "samay.db"))
# Set SAMAY_COOKIE_SECURE=1 when serving over HTTPS so the sign-in cookie is never sent over plain HTTP.
COOKIE_SECURE = os.environ.get("SAMAY_COOKIE_SECURE", "0") == "1"
# Anyone can create a new college account from the sign-in page. Turn off with SAMAY_SIGNUP=0.
SIGNUP = os.environ.get("SAMAY_SIGNUP", "1") == "1"
# One-click sign-in for the seed demo accounts (no password). Turn off for a real launch: SAMAY_DEMO_LOGIN=0.
DEMO_LOGIN = os.environ.get("SAMAY_DEMO_LOGIN", "1") == "1"
# On a public demo server: generate and publish the demo college's timetable and turn on its student code at start.
# On by default on Render (it sets RENDER=true), where the free plan starts with an empty database after every restart.
DEMO_READY = os.environ.get("SAMAY_DEMO_READY", "1" if os.environ.get("RENDER") else "0") == "1"
SOLVE_SECONDS = float(os.environ.get("SAMAY_SOLVE_SECONDS", "120"))  # time limit for one generation run (a real college of ~25 sections needs ~1 min)
SOLVER_WORKERS = int(os.environ.get("SAMAY_SOLVER_WORKERS", "8"))  # CPU threads per run; lower on small servers
ALLOWED_ORIGINS = [o for o in os.environ.get("SAMAY_ORIGINS", "http://localhost:5500").split(",") if o]
# The AI assistant needs an Anthropic API key in the environment (never in the code). SAMAY_ASSISTANT=0 turns it off.
ASSISTANT = os.environ.get("SAMAY_ASSISTANT", "1") != "0" and bool(os.environ.get("ANTHROPIC_API_KEY"))
# Email for invites and password resets (any SMTP server). Without it, the app shows links to copy instead.
SMTP_HOST = os.environ.get("SAMAY_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SAMAY_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SAMAY_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SAMAY_SMTP_PASSWORD", "")
EMAIL_FROM = os.environ.get("SAMAY_EMAIL_FROM", "")  # e.g. "Samay <timetable@yourcollege.edu>"
# The site's public address, used in emailed links (e.g. https://samay-timetable.onrender.com).
PUBLIC_URL = os.environ.get("SAMAY_PUBLIC_URL", "").rstrip("/")
# Most AI assistant questions per day for the whole site (protects the API key on a public demo). 0 = no limit.
ASSISTANT_DAILY_LIMIT = int(os.environ.get("SAMAY_ASSISTANT_DAILY_LIMIT", "60"))
