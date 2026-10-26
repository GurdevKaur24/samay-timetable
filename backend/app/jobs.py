"""Timetable generation runs in the background so the page can show progress instead of waiting.

A job belongs to one college. Only one generation runs per college at a time; starting again while one is running
returns the running job. A timetable is saved only if the independent clash checker finds no problems.
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from solver.metrics import metrics
from solver.model import solve
from solver.validator import validate

from . import config
from .db import Database


@dataclass
class Job:
    id: str
    college_id: str
    status: str = "queued"  # queued → running → done | failed
    message: str = "Waiting to start."
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    timetable_version: int | None = None
    locked: list[dict] = field(default_factory=list)
    # stage: preparing → searching → improving; found: a timetable with no clashes exists (it can be used now)
    progress: dict = field(default_factory=lambda: {"stage": "preparing", "found": False})
    stop: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "status", "message", "created_at", "finished_at", "timetable_version", "progress")}


def matching_locks(data: dict, locked: list[dict]) -> tuple[list[dict], int]:
    """Keep only locks that still point at the same class (same subject and group) in the current data.
    Assignment ids can shift when classes are added or deleted, so the subject and group are checked too."""
    by_id = {a["id"]: a for a in data["assignments"]}
    keep = []
    for lock in locked:
        a = by_id.get(lock.get("assignment"))
        if a and a["subject"] == lock.get("subject") and a["group"] == lock.get("group"):
            keep.append({k: lock[k] for k in ("assignment", "subject", "group", "day", "start", "room")})
    return keep, len(locked) - len(keep)


class JobRunner:
    def __init__(self, db: Database, time_limit: float = 30.0, workers: int = 2):
        self.db, self.time_limit = db, time_limit
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="generate")
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def start(self, college_id: str, locked: list[dict] | None = None) -> Job:
        with self.lock:
            for job in self.jobs.values():
                if job.college_id == college_id and job.status in ("queued", "running"):
                    return job
            job = Job(id=uuid.uuid4().hex, college_id=college_id, locked=list(locked or []))
            self.jobs[job.id] = job
        self.pool.submit(self._run, job)
        return job

    def get(self, college_id: str, job_id: str) -> Job | None:
        """A job, but only for the college that started it."""
        job = self.jobs.get(job_id)
        return job if job is not None and job.college_id == college_id else None

    def stop(self, college_id: str, job_id: str) -> Job | None:
        """Stop a run now and keep the best timetable found so far (if any)."""
        job = self.get(college_id, job_id)
        if job is not None:
            job.stop.set()
        return job

    @staticmethod
    def _progress(job: Job, update: dict) -> None:
        """Keep the stage, and how much better the timetable is than the first one found (0-100%)."""
        progress = job.progress
        progress.update({k: v for k, v in update.items() if k != "cost"})
        if update.get("cost") is not None:
            progress.setdefault("first_cost", update["cost"])
            first = progress["first_cost"]
            progress["better_pct"] = round(100 * (first - update["cost"]) / first) if first else 0
            progress["improvements"] = progress.get("improvements", 0) + 1

    def _run(self, job: Job) -> None:
        job.status, job.message = "running", "Generating the timetable."
        try:
            loaded = self.db.get_college_data_with_version(job.college_id)
            if loaded is None:
                raise RuntimeError("Your college's data couldn't be found.")
            data, data_version = loaded
            locked, dropped = matching_locks(data, job.locked)
            result = solve(data, time_limit=self.time_limit, fixed=locked, workers=config.SOLVER_WORKERS, patience=config.SOLVE_PATIENCE,
                           stop=job.stop, on_progress=lambda **p: self._progress(job, p),
                           max_rooms=config.MAX_ROOM_CHOICES or None, max_memory_mb=config.SOLVER_MEMORY_MB or None)
            if result["status"] == "stopped":
                job.status, job.message = "failed", "Stopped before a timetable was found. Nothing was saved."
                return
            if result["status"] not in ("optimal", "feasible"):
                job.status, job.message = "failed", f"{result['message']} Run the pre-check to see what to change."
                return
            violations = validate(data, result["entries"])
            if violations:  # never save a timetable the clash checker rejects
                job.status = "failed"
                job.message = "The generated timetable didn't pass the clash check, so it wasn't saved: " + violations[0]["message"]
                return
            job.timetable_version = self.db.save_timetable(job.college_id, {
                "built_from": data_version,
                "solver_status": result["status"],
                "seconds": result["seconds"],
                "entries": result["entries"],
                "metrics": metrics(data, result["entries"]),
                "locked": locked,
                "data": data,  # the exact data it was built from, so old versions still display correctly
            })
            job.status = "done"
            job.message = f"Timetable v{job.timetable_version} made and checked: 0 clashes."
            if job.stop.is_set():
                job.message += " You stopped it early, so it may have a few more gaps; make it again any time for a better one."
            if locked:
                job.message += f" {len(locked)} locked class(es) stayed where they were."
            if dropped:
                job.message += f" {dropped} locked class(es) no longer matched your data and were unlocked."
        except Exception as e:  # keep the server running and tell the user plainly
            job.status, job.message = "failed", f"Generation stopped unexpectedly: {e}"
        finally:
            job.finished_at = time.time()
