"""Who is signed in. `current_user` is the only way a request gets a college id: from the user's session,
never from the URL or the request body."""

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from .db import Database

COOKIE_NAME = "samay_session"

ROLES = {"coordinator": "Timetable coordinator", "teacher": "Teacher"}


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    name: str
    role: str
    college_id: str
    college_name: str
    teacher_id: str | None = None  # set for teacher accounts: their record in the college data


def get_db(request: Request) -> Database:
    return request.app.state.db


def current_user(request: Request, db: Database = Depends(get_db)) -> CurrentUser:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")
    row = db.user_for_token(token)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has ended. Please sign in again.")
    return user_from_row(row)


def user_from_row(row) -> CurrentUser:
    return CurrentUser(row["id"], row["email"], row["name"], row["role"], row["college_id"], row["college_name"], row["teacher_id"])


def coordinator_only(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """Managing data, generating, editing and publishing timetables, and accounts are for coordinators only."""
    if user.role != "coordinator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only timetable coordinators can do that.")
    return user


def teacher_only(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.role != "teacher" or not user.teacher_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This page is for teachers.")
    return user


class LoginLimiter:
    """Slows down password guessing: at most `limit` failed sign-ins per email in `window` seconds."""

    def __init__(self, limit: int = 5, window: float = 15 * 60):
        self.limit, self.window = limit, window
        self.failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, email: str) -> deque[float]:
        q, cutoff = self.failures[email], time.time() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, email: str) -> bool:
        return len(self._recent(email)) >= self.limit

    def failed(self, email: str) -> None:
        self._recent(email).append(time.time())

    def succeeded(self, email: str) -> None:
        self.failures.pop(email, None)
