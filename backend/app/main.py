from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .auth import DailyQuota, LoginLimiter
from .db import Database
from .jobs import JobRunner
from .routers import assistant, auth, college, students, teacher, timetables, users
from .seed import seed


AUTO = object()


def default_assistant():
    """The real assistant (Claude), if an API key is set; None otherwise (the page then uses its built-in helper)."""
    if not config.ASSISTANT:
        return None
    from functools import partial

    import anthropic

    from .services.assistant import chat
    return partial(chat, anthropic.Anthropic())


class FreshStaticFiles(StaticFiles):
    """Browsers must check for a newer page each time (cheap: unchanged files answer 304), so updates show at once."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(db_path: str | Path | None = None, seed_if_empty: bool = True, solve_seconds: float | None = None,
               demo_login: bool | None = None, signup: bool | None = None, assistant_chat=AUTO) -> FastAPI:
    app = FastAPI(title="Samay Timetable API")
    app.state.demo_login = config.DEMO_LOGIN if demo_login is None else demo_login
    app.state.signup = config.SIGNUP if signup is None else signup
    app.state.db = Database(db_path or config.DB_PATH)
    app.state.jobs = JobRunner(app.state.db, time_limit=solve_seconds or config.SOLVE_SECONDS)
    app.state.login_limiter = LoginLimiter()
    app.state.student_limiter = LoginLimiter(limit=10)  # wrong student codes, per address
    app.state.cookie_secure = config.COOKIE_SECURE
    app.state.assistant_chat = default_assistant() if assistant_chat is AUTO else assistant_chat
    app.state.assistant_quota = DailyQuota(config.ASSISTANT_DAILY_LIMIT)
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
    app.include_router(teacher.router)
    app.include_router(assistant.router)
    app.include_router(students.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": "samay", "demo_login": app.state.demo_login, "signup": app.state.signup,
                "assistant": app.state.assistant_chat is not None}

    # The web page: same origin as the API, so the sign-in cookie just works. Mounted last so /api routes win.
    if config.WEB_DIR.is_dir():
        app.mount("/", FreshStaticFiles(directory=config.WEB_DIR, html=True), name="web")

    return app


app = create_app()
