from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .auth import LoginLimiter
from .db import Database
from .jobs import JobRunner
from .routers import auth, college, timetables
from .seed import seed


def create_app(db_path: str | Path | None = None, seed_if_empty: bool = True, solve_seconds: float | None = None) -> FastAPI:
    app = FastAPI(title="Samay Timetable API")
    app.state.db = Database(db_path or config.DB_PATH)
    app.state.jobs = JobRunner(app.state.db, time_limit=solve_seconds or config.SOLVE_SECONDS)
    app.state.login_limiter = LoginLimiter()
    app.state.cookie_secure = config.COOKIE_SECURE
    if seed_if_empty and app.state.db.college_count() == 0:
        seed(app.state.db)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.ALLOWED_ORIGINS,
        allow_credentials=True,  # the sign-in cookie
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router)
    app.include_router(college.router)
    app.include_router(timetables.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": "samay"}

    # The web page: same origin as the API, so the sign-in cookie just works. Mounted last so /api routes win.
    if config.WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")

    return app


app = create_app()
