"""Timetable generation runs in the background so the page can show progress instead of waiting.

A job belongs to one college. Only one generation runs per college at a time; starting again while one is running
returns the running job. A timetable is saved only if the independent clash checker finds no problems.
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from solver.metrics import metrics
from solver.model import solve
from solver.validator import validate

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

    def public(self) -> dict:
        d = asdict(self)
        d.pop("college_id")
        return d


class JobRunner:
    def __init__(self, db: Database, time_limit: float = 30.0, workers: int = 2):
        self.db, self.time_limit = db, time_limit
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="generate")
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def start(self, college_id: str) -> Job:
        with self.lock:
            for job in self.jobs.values():
                if job.college_id == college_id and job.status in ("queued", "running"):
                    return job
            job = Job(id=uuid.uuid4().hex, college_id=college_id)
            self.jobs[job.id] = job
        self.pool.submit(self._run, job)
        return job

    def get(self, college_id: str, job_id: str) -> Job | None:
        """A job, but only for the college that started it."""
        job = self.jobs.get(job_id)
        return job if job is not None and job.college_id == college_id else None

    def _run(self, job: Job) -> None:
        job.status, job.message = "running", "Generating the timetable."
        try:
            loaded = self.db.get_college_data_with_version(job.college_id)
            if loaded is None:
                raise RuntimeError("Your college's data couldn't be found.")
            data, data_version = loaded
            result = solve(data, time_limit=self.time_limit)
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
                "data": data,  # the exact data it was built from, so old versions still display correctly
            })
            job.status = "done"
            job.message = f"Timetable v{job.timetable_version} generated and checked: 0 clashes."
        except Exception as e:  # keep the server running and tell the user plainly
            job.status, job.message = "failed", f"Generation stopped unexpectedly: {e}"
        finally:
            job.finished_at = time.time()
