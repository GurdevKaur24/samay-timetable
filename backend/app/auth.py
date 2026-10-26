"""Who is signed in. `current_user` is the only way a request gets a college id: from the user's session,
never from the URL or the request body."""

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from .db import Database

COOKIE_NAME = "samay_session"

ROLES = {"coordinator": "Timetable coordinator", "hod": "Head of department", "teacher": "Teacher"}


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    name: str
    role: str
    college_id: str
    college_name: str
    teacher_id: str | None = None  # set for teacher accounts: their record in the college data
    dept_id: str | None = None     # set for heads of department: the department they manage


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
    return CurrentUser(row["id"], row["email"], row["name"], row["role"], row["college_id"], row["college_name"], row["teacher_id"], row["dept_id"])


def coordinator_only(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """Managing data, generating, editing and publishing timetables, and accounts are for coordinators only."""
    if user.role != "coordinator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only timetable coordinators can do that.")
    return user


def coordinator_or_hod(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """Reading and saving college data: heads of department may save only their own department's part (checked on save)."""
    if user.role == "coordinator" or (user.role == "hod" and user.dept_id):
        return user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only timetable coordinators can do that.")


def teacher_only(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.role != "teacher" or not user.teacher_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This page is for teachers.")
    return user


class PersonQuota:
    """At most `limit` uses per calendar day for each person (or phone); 0 means no limit."""

    def __init__(self, limit: int):
        self.limit, self.day, self.used = limit, None, defaultdict(int)

    def take(self, who: str) -> bool:
        today = time.strftime("%Y-%m-%d")
        if today != self.day:
            self.day, self.used = today, defaultdict(int)
        if self.limit and self.used[who] >= self.limit:
            return False
        self.used[who] += 1
        return True


class DailyQuota:
    """At most `limit` uses per calendar day (server time) for the whole site; 0 means no limit."""

    def __init__(self, limit: int):
        self.limit, self.day, self.used = limit, None, 0

    def take(self) -> bool:
        today = time.strftime("%Y-%m-%d")
        if today != self.day:
            self.day, self.used = today, 0
        if self.limit and self.used >= self.limit:
            return False
        self.used += 1
        return True


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
