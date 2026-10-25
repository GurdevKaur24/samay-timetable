"""SQLite storage. Every function that reads or writes college data takes the college id explicitly; the web layer
only ever passes the signed-in user's college id."""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .security import hash_password, new_token, token_hash
from .services.fingerprint import schedule_fingerprint

SCHEMA = """
CREATE TABLE IF NOT EXISTS colleges (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    created_at         REAL NOT NULL,
    published_version  INTEGER,
    published_at       REAL
);
CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    role           TEXT NOT NULL,
    college_id     TEXT NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
    password_hash  TEXT NOT NULL,
    teacher_id     TEXT,
    dept_id        TEXT
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
CREATE TABLE IF NOT EXISTS student_sessions (
    token_hash  TEXT PRIMARY KEY,
    college_id  TEXT NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS password_tokens (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    expires_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS timetable_numbers (
    college_id  TEXT PRIMARY KEY REFERENCES colleges(id) ON DELETE CASCADE,
    last        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_college ON users(college_id);
CREATE INDEX IF NOT EXISTS idx_timetables_college ON timetables(college_id);
"""

# Columns added after the first release; older databases get them on start.
ADDED_COLUMNS = {
    "colleges": [("published_version", "INTEGER"), ("published_at", "REAL"), ("student_code", "TEXT")],
    "users": [("teacher_id", "TEXT"), ("dept_id", "TEXT")],
}

SESSION_SECONDS = 12 * 60 * 60
NO_PASSWORD = "!"  # an invited person who hasn't set a password yet: no password matches it
LINK_SECONDS = {"invite": 7 * 24 * 60 * 60, "reset": 60 * 60}
STUDENT_SESSION_SECONDS = 180 * 24 * 60 * 60  # a phone remembers the college for a semester


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            for table, columns in ADDED_COLUMNS.items():
                have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                for name, kind in columns:
                    if name not in have:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_colleges_student_code ON colleges(student_code)")

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

    def update_college_data(self, college_id: str, change, attempts: int = 5) -> tuple[dict, int] | None:
        """Apply `change(data) -> data` to the latest data and save it, retrying if someone saved in the meantime.
        Used for small changes made by people who don't edit the whole college (a teacher's own free times)."""
        for _ in range(attempts):
            loaded = self.get_college_data_with_version(college_id)
            if loaded is None:
                return None
            data, version = loaded
            new = change(data)
            saved = self.save_college_data(college_id, new, expected_version=version)
            if saved is not None:
                return new, saved
        return None

    def save_college_data(self, college_id: str, data: dict, expected_version: int | None = None) -> int | None:
        """Replace a college's data; returns the new data version. With `expected_version`, saves only if nobody else
        saved in the meantime (returns None otherwise)."""
        with self.connect() as conn:
            if expected_version is None:
                cur = conn.execute("UPDATE college_data SET data = ?, version = version + 1, updated_at = ? WHERE college_id = ?",
                                   (json.dumps(data), time.time(), college_id))
            else:
                cur = conn.execute("UPDATE college_data SET data = ?, version = version + 1, updated_at = ? WHERE college_id = ? AND version = ?",
                                   (json.dumps(data), time.time(), college_id, expected_version))
            if cur.rowcount == 0:
                return None
            return conn.execute("SELECT version FROM college_data WHERE college_id = ?", (college_id,)).fetchone()["version"]

    # ---- timetables -----------------------------------------------------------------------------------------
    def save_timetable(self, college_id: str, result: dict) -> int:
        """Store a checked timetable as the college's next version number; returns that number."""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Numbers only go up, even after a version is deleted, so "v3" always means the same timetable.
            highest = conn.execute("SELECT COALESCE(MAX(version), 0) FROM timetables WHERE college_id = ?", (college_id,)).fetchone()[0]
            row = conn.execute("SELECT last FROM timetable_numbers WHERE college_id = ?", (college_id,)).fetchone()
            version = max(highest, row["last"] if row else 0) + 1
            conn.execute("INSERT INTO timetable_numbers (college_id, last) VALUES (?, ?) ON CONFLICT(college_id) DO UPDATE SET last = excluded.last",
                         (college_id, version))
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
                        "score": result["metrics"]["score"], "seconds": result["seconds"],
                        "how": result.get("solver_status", "optimal"), "edited_from": result.get("edited_from"),
                        "restored_from": result.get("restored_from"), "locked": len(result.get("locked", [])),
                        "fingerprint": schedule_fingerprint(result["data"])})
        return out

    def update_timetable_locks(self, college_id: str, version: int, locked: list[dict]) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT result FROM timetables WHERE college_id = ? AND version = ?", (college_id, version)).fetchone()
            if row is None:
                return
            result = json.loads(row["result"])
            result["locked"] = locked
            conn.execute("UPDATE timetables SET result = ? WHERE college_id = ? AND version = ?", (json.dumps(result), college_id, version))

    def published(self, college_id: str) -> dict | None:
        """The version teachers (and later students) see: {version, published_at}, or None."""
        with self.connect() as conn:
            row = conn.execute("SELECT published_version, published_at FROM colleges WHERE id = ?", (college_id,)).fetchone()
        if row is None or row["published_version"] is None:
            return None
        return {"version": row["published_version"], "published_at": row["published_at"]}

    def set_published(self, college_id: str, version: int | None) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE colleges SET published_version = ?, published_at = ? WHERE id = ?",
                         (version, time.time() if version is not None else None, college_id))

    def delete_timetable(self, college_id: str, version: int) -> bool:
        with self.connect() as conn:
            return conn.execute("DELETE FROM timetables WHERE college_id = ? AND version = ?", (college_id, version)).rowcount > 0

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

    # ---- student access: one shared code per college --------------------------------------------------------
    def student_code(self, college_id: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT student_code FROM colleges WHERE id = ?", (college_id,)).fetchone()
        return row["student_code"] if row else None

    def set_student_code(self, college_id: str, code: str | None) -> None:
        """A new code (or None to turn student access off). Phones that used the old code are signed out."""
        with self.connect() as conn:
            conn.execute("UPDATE colleges SET student_code = ? WHERE id = ?", (code, college_id))
            conn.execute("DELETE FROM student_sessions WHERE college_id = ?", (college_id,))

    def college_for_student_code(self, code: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT id, name FROM colleges WHERE student_code = ?", (code,)).fetchone()

    def create_student_session(self, college_id: str) -> str:
        token, now = new_token(), time.time()
        with self.connect() as conn:
            conn.execute("DELETE FROM student_sessions WHERE expires_at < ?", (now,))
            conn.execute("INSERT INTO student_sessions (token_hash, college_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                         (token_hash(token), college_id, now, now + STUDENT_SESSION_SECONDS))
        return token

    def college_for_student_token(self, token: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """SELECT c.id, c.name FROM student_sessions s JOIN colleges c ON c.id = s.college_id
                   WHERE s.token_hash = ? AND s.expires_at > ? AND c.student_code IS NOT NULL""",
                (token_hash(token), time.time()),
            ).fetchone()

    def delete_student_session(self, token: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM student_sessions WHERE token_hash = ?", (token_hash(token),))

    # ---- users and sessions ---------------------------------------------------------------------------------
    def add_user(self, email: str, name: str, role: str, college_id: str, password: str | None, teacher_id: str | None = None,
                 dept_id: str | None = None) -> int:
        """`teacher_id` links a teacher's account to their record in the college data; `dept_id` a head of department's.
        Without a password the person is invited: they choose one through an invite link."""
        with self.connect() as conn:
            cur = conn.execute("INSERT INTO users (email, name, role, college_id, password_hash, teacher_id, dept_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (email.strip().lower(), name, role, college_id, hash_password(password) if password else NO_PASSWORD, teacher_id, dept_id))
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
                """SELECT u.id, u.email, u.name, u.role, u.college_id, u.teacher_id, u.dept_id, c.name AS college_name
                   FROM sessions s JOIN users u ON u.id = s.user_id JOIN colleges c ON c.id = u.college_id
                   WHERE s.token_hash = ? AND s.expires_at > ?""",
                (token_hash(token), time.time()),
            ).fetchone()

    def delete_session(self, token: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))

    def list_users(self, college_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT id, email, name, role, teacher_id, dept_id, password_hash = ? AS invited FROM users WHERE college_id = ? ORDER BY name",
                                (NO_PASSWORD, college_id)).fetchall()

    def user_for_token_college(self, college_id: str) -> str:
        """A college's name (for emails)."""
        with self.connect() as conn:
            row = conn.execute("SELECT name FROM colleges WHERE id = ?", (college_id,)).fetchone()
        return row["name"] if row else ""

    def user_in_college(self, college_id: str, user_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT id, email, name, password_hash = ? AS invited FROM users WHERE id = ? AND college_id = ?",
                                (NO_PASSWORD, user_id, college_id)).fetchone()

    # ---- one-time links: invites (7 days) and password resets (1 hour) ---------------------------------------
    def create_password_token(self, user_id: int, kind: str) -> str:
        """A new link for this person; any earlier link of either kind stops working."""
        token, now = new_token(), time.time()
        with self.connect() as conn:
            conn.execute("DELETE FROM password_tokens WHERE user_id = ? OR expires_at < ?", (user_id, now))
            conn.execute("INSERT INTO password_tokens (token_hash, user_id, kind, expires_at) VALUES (?, ?, ?, ?)",
                         (token_hash(token), user_id, kind, now + LINK_SECONDS[kind]))
        return token

    def password_token(self, token: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """SELECT t.kind, u.id AS user_id, u.name, u.email, c.name AS college_name
                   FROM password_tokens t JOIN users u ON u.id = t.user_id JOIN colleges c ON c.id = u.college_id
                   WHERE t.token_hash = ? AND t.expires_at > ?""",
                (token_hash(token), time.time()),
            ).fetchone()

    def use_password_token(self, token: str, password: str) -> int | None:
        """Set the person's password from a valid link (used once); every session they had ends."""
        with self.connect() as conn:
            row = conn.execute("SELECT user_id FROM password_tokens WHERE token_hash = ? AND expires_at > ?",
                               (token_hash(token), time.time())).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), row["user_id"]))
            conn.execute("DELETE FROM password_tokens WHERE user_id = ?", (row["user_id"],))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
            return row["user_id"]

    def delete_user(self, college_id: str, user_id: int) -> bool:
        """Removes a user of this college only; their sessions end with them."""
        with self.connect() as conn:
            return conn.execute("DELETE FROM users WHERE id = ? AND college_id = ?", (user_id, college_id)).rowcount > 0

    def password_hash(self, user_id: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["password_hash"] if row else None

    def set_password(self, user_id: int, password: str, keep_token: str | None = None) -> None:
        """New password; every other session of this user is signed out."""
        with self.connect() as conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))
            conn.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, token_hash(keep_token or "")))
