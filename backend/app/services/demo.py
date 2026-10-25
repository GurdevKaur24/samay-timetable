"""A public demo server starts empty after every restart (no disk on the free plan). With SAMAY_DEMO_READY=1 it gets
the full demo college ready in the background: a timetable generated (through the normal job, so it passes the clash
checker), published, and student access on with a fixed code, so every role works as soon as someone opens the link."""

import threading
import time

READY = {"demo-eng": "DEMO2026"}  # college id -> its student code (shown as DEMO-2026)


def make_ready(app, college_id: str, code: str, wait: float = 900) -> None:
    db, jobs = app.state.db, app.state.jobs
    if db.get_college_data(college_id) is None:
        return
    if db.student_code(college_id) is None:
        db.set_student_code(college_id, code)
    if db.published(college_id) is not None:
        return  # already ready (or a person published their own version)
    job = jobs.start(college_id, [])
    end = time.time() + wait
    while job.status in ("queued", "running") and time.time() < end:
        time.sleep(1)
    if job.status == "done":
        db.set_published(college_id, job.timetable_version)


def prepare_demos(app) -> None:
    for college_id, code in READY.items():
        make_ready(app, college_id, code)


def start(app) -> None:
    threading.Thread(target=prepare_demos, args=(app,), daemon=True, name="demo-ready").start()
