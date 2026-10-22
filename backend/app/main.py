from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .auth import LoginLimiter
from .db import Database
from .jobs import JobRunner
from .routers import auth, college, timetables, users
from .seed import seed


class FreshStaticFiles(StaticFiles):
    """Browsers must check for a newer page each time (cheap: unchanged files answer 304), so updates show at once."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(db_path: str | Path | None = None, seed_if_empty: bool = True, solve_seconds: float | None = None,
               demo_login: bool | None = None, signup: bool | None = None) -> FastAPI:
    app = FastAPI(title="Samay Timetable API")
    app.state.demo_login = config.DEMO_LOGIN if demo_login is None else demo_login
    app.state.signup = config.SIGNUP if signup is None else signup
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
    app.include_router(users.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": "samay", "demo_login": app.state.demo_login, "signup": app.state.signup}

    # The web page: same origin as the API, so the sign-in cookie just works. Mounted last so /api routes win.
    if config.WEB_DIR.is_dir():
        app.mount("/", FreshStaticFiles(directory=config.WEB_DIR, html=True), name="web")

    return app


app = create_app()
