"""SQLite storage. Every function that reads or writes college data takes the college id explicitly; the web layer
only ever passes the signed-in user's college id."""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .security import hash_password, new_token, token_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS colleges (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    role           TEXT NOT NULL,
    college_id     TEXT NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
    password_hash  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS college_data (
    college_id  TEXT PRIMARY KEY REFERENCES colleges(id) ON DELETE CASCADE,
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS timetables (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    college_id  TEXT NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    created_at  REAL NOT NULL,
    status      TEXT NOT NULL,
    result      TEXT NOT NULL,
    UNIQUE (college_id, version)
);
CREATE INDEX IF NOT EXISTS idx_users_college ON users(college_id);
CREATE INDEX IF NOT EXISTS idx_timetables_college ON timetables(college_id);
"""

SESSION_SECONDS = 12 * 60 * 60


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- colleges -------------------------------------------------------------------------------------------
    def college_count(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM colleges").fetchone()[0]

    def add_college(self, college_id: str, name: str, data: dict) -> None:
        now = time.time()
        with self.connect() as conn:
            conn.execute("INSERT INTO colleges (id, name, created_at) VALUES (?, ?, ?)", (college_id, name, now))
            conn.execute("INSERT INTO college_data (college_id, data, version, updated_at) VALUES (?, ?, 1, ?)",
                         (college_id, json.dumps(data), now))

    def get_college_data(self, college_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT data FROM college_data WHERE college_id = ?", (college_id,)).fetchone()
        return json.loads(row["data"]) if row else None

    def get_data_version(self, college_id: str) -> int | None:
        with self.connect() as conn:
            row = conn.execute("SELECT version FROM college_data WHERE college_id = ?", (college_id,)).fetchone()
        return row["version"] if row else None

    def get_college_data_with_version(self, college_id: str) -> tuple[dict, int] | None:
        """Data and its version read together, so a timetable always records exactly what it was built from."""
        with self.connect() as conn:
            row = conn.execute("SELECT data, version FROM college_data WHERE college_id = ?", (college_id,)).fetchone()
        return (json.loads(row["data"]), row["version"]) if row else None

    def save_college_data(self, college_id: str, data: dict) -> int:
        """Replace a college's data; returns the new data version."""
        with self.connect() as conn:
            conn.execute("UPDATE college_data SET data = ?, version = version + 1, updated_at = ? WHERE college_id = ?",
                         (json.dumps(data), time.time(), college_id))
            return conn.execute("SELECT version FROM college_data WHERE college_id = ?", (college_id,)).fetchone()["version"]

    # ---- timetables -----------------------------------------------------------------------------------------
    def save_timetable(self, college_id: str, result: dict) -> int:
        """Store a checked timetable as the college's next version number; returns that number."""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM timetables WHERE college_id = ?", (college_id,)).fetchone()[0]
            conn.execute("INSERT INTO timetables (college_id, version, created_at, status, result) VALUES (?, ?, ?, 'ok', ?)",
                         (college_id, version, time.time(), json.dumps(result)))
        return version

    def list_timetables(self, college_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT version, created_at, result FROM timetables WHERE college_id = ? ORDER BY version DESC",
                                (college_id,)).fetchall()
        out = []
        for r in rows:
            result = json.loads(r["result"])
            out.append({"version": r["version"], "created_at": r["created_at"], "built_from": result["built_from"],
                        "score": result["metrics"]["score"], "seconds": result["seconds"]})
        return out

    def get_timetable(self, college_id: str, version: int | None = None) -> dict | None:
        """One version of a college's timetable (the latest if no version is given)."""
        with self.connect() as conn:
            if version is None:
                row = conn.execute("SELECT version, created_at, result FROM timetables WHERE college_id = ? ORDER BY version DESC LIMIT 1",
                                   (college_id,)).fetchone()
            else:
                row = conn.execute("SELECT version, created_at, result FROM timetables WHERE college_id = ? AND version = ?",
                                   (college_id, version)).fetchone()
        if row is None:
            return None
        return {"version": row["version"], "created_at": row["created_at"], **json.loads(row["result"])}

    # ---- users and sessions ---------------------------------------------------------------------------------
    def add_user(self, email: str, name: str, role: str, college_id: str, password: str) -> int:
        with self.connect() as conn:
            cur = conn.execute("INSERT INTO users (email, name, role, college_id, password_hash) VALUES (?, ?, ?, ?, ?)",
                               (email.strip().lower(), name, role, college_id, hash_password(password)))
            return cur.lastrowid

    def find_user_by_email(self, email: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()

    def create_session(self, user_id: int, seconds: int = SESSION_SECONDS) -> str:
        token, now = new_token(), time.time()
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                         (token_hash(token), user_id, now, now + seconds))
        return token

    def user_for_token(self, token: str) -> sqlite3.Row | None:
        """The signed-in user for a session token, with their college; None if the session is unknown or expired."""
        with self.connect() as conn:
            return conn.execute(
                """SELECT u.id, u.email, u.name, u.role, u.college_id, c.name AS college_name
                   FROM sessions s JOIN users u ON u.id = s.user_id JOIN colleges c ON c.id = u.college_id
                   WHERE s.token_hash = ? AND s.expires_at > ?""",
                (token_hash(token), time.time()),
            ).fetchone()

    def delete_session(self, token: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
