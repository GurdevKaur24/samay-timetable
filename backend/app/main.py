from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .auth import LoginLimiter
from .db import Database
from .routers import auth, college
from .seed import seed


def create_app(db_path: str | Path | None = None, seed_if_empty: bool = True) -> FastAPI:
    app = FastAPI(title="Samay Timetable API")
    app.state.db = Database(db_path or config.DB_PATH)
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

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
