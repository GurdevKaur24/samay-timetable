"""Pre-check, generation and saved timetables for the signed-in user's own college."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from solver.metrics import metrics
from solver.validator import validate

from ..auth import CurrentUser, coordinator_only, get_db
from ..db import Database
from ..services.fingerprint import schedule_fingerprint
from ..services.precheck import precheck

router = APIRouter(prefix="/api", tags=["timetables"])


def own_data(user: CurrentUser, db: Database) -> tuple[dict, int]:
    loaded = db.get_college_data_with_version(user.college_id)
    if loaded is None:
        raise HTTPException(404, "Your college's data couldn't be found.")
    return loaded


class Lock(BaseModel):
    """A locked session: it stays exactly here when the timetable is generated again."""
    assignment: str
    subject: str
    group: str
    day: str
    start: int = Field(ge=1)
    room: str


def locks_in(entries: list[dict], locked: list[Lock]) -> list[dict]:
    """Only locks that match a session in these entries (same class, day, first period and room)."""
    starts = {}
    for e in entries:
        key = (e["assignment"], e["day"])
        if key not in starts or e["period"] < starts[key][0]:
            starts[key] = (e["period"], e["room"])
    return [lock.model_dump() for lock in locked if starts.get((lock.assignment, lock.day)) == (lock.start, lock.room)]


@router.get("/precheck")
def run_precheck(user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    data, _ = own_data(user, db)
    items = precheck(data)
    errors = sum(1 for i in items if i["level"] == "error")
    return {"ready": errors == 0, "errors": errors, "warnings": sum(1 for i in items if i["level"] == "warn"), "items": items}


class GenerateIn(BaseModel):
    locked: list[Lock] = []


@router.post("/timetables", status_code=status.HTTP_202_ACCEPTED)
def generate(request: Request, body: GenerateIn | None = None, user: CurrentUser = Depends(coordinator_only)):
    locked = [lock.model_dump() for lock in (body.locked if body else [])]
    return request.app.state.jobs.start(user.college_id, locked).public()


@router.get("/jobs/{job_id}")
def job_status(job_id: str, request: Request, user: CurrentUser = Depends(coordinator_only)):
    job = request.app.state.jobs.get(user.college_id, job_id)
    if job is None:
        raise HTTPException(404, "That generation run wasn't found.")
    return job.public()


def with_freshness(timetable: dict, current_fingerprint: str) -> dict:
    """A timetable is out of date when data that affects scheduling changed after it was made."""
    timetable["out_of_date"] = timetable.pop("fingerprint", None) != current_fingerprint
    return timetable


@router.get("/timetables")
def list_versions(user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    data, current = own_data(user, db)
    fp = schedule_fingerprint(data)
    return {"data_version": current, "published": db.published(user.college_id),
            "timetables": [with_freshness(t, fp) for t in db.list_timetables(user.college_id)]}


@router.get("/timetables/latest")
def latest(user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    return fetch(None, user, db)


@router.get("/timetables/{version}")
def one_version(version: int, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    return fetch(version, user, db)


def fetch(version: int | None, user: CurrentUser, db: Database) -> dict:
    timetable = db.get_timetable(user.college_id, version)
    if timetable is None:
        raise HTTPException(404, "No timetable yet. Generate one first." if version is None else f"There's no timetable v{version}.")
    timetable.setdefault("locked", [])
    timetable["fingerprint"] = schedule_fingerprint(timetable["data"])
    timetable["published"] = db.published(user.college_id)
    return with_freshness(timetable, schedule_fingerprint(own_data(user, db)[0]))


def current_base(version: int, user: CurrentUser, db: Database) -> tuple[dict, dict, int]:
    """A saved version plus the college's current data; refuses if scheduling data changed after that version was made."""
    base = db.get_timetable(user.college_id, version)
    if base is None:
        raise HTTPException(404, f"There's no timetable v{version}.")
    data, current = own_data(user, db)
    if schedule_fingerprint(base["data"]) != schedule_fingerprint(data):
        raise HTTPException(409, "Your college's data changed after this timetable was made. Generate again first.")
    return base, data, current


def save_checked(user: CurrentUser, db: Database, data: dict, current: int, entries: list[dict], locked: list[dict], **extra) -> int:
    problems = validate(data, entries)
    if problems:
        raise HTTPException(422, {"message": f"That change wasn't saved: it would cause {len(problems)} problem(s).",
                                  "problems": [p["message"] for p in problems]})
    return db.save_timetable(user.college_id, {
        "built_from": current, "seconds": 0, "entries": entries, "metrics": metrics(data, entries),
        "locked": locked, "data": data, **extra,
    })


class Revision(BaseModel):
    entries: list[dict]
    locked: list[Lock] = []


@router.post("/timetables/{version}/revise", status_code=status.HTTP_201_CREATED)
def revise(version: int, body: Revision, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    """Save a hand-edited copy of a timetable (a moved or swapped class, or a change approved in the assistant) as a
    new version. It's saved only if the clash checker finds no problems."""
    _, data, current = current_base(version, user, db)
    entries = [{k: e.get(k) for k in ("assignment", "day", "period", "room")} for e in body.entries]
    new_version = save_checked(user, db, data, current, entries, locks_in(entries, body.locked), solver_status="edited", edited_from=version)
    return {"version": new_version, "message": f"Saved as timetable v{new_version}: 0 clashes."}


class LocksIn(BaseModel):
    locked: list[Lock]


@router.put("/timetables/{version}/locks")
def set_locks(version: int, body: LocksIn, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    """Lock or unlock classes on a version. Locks don't move anything, so no new version is made."""
    timetable = db.get_timetable(user.college_id, version)
    if timetable is None:
        raise HTTPException(404, f"There's no timetable v{version}.")
    kept = locks_in(timetable["entries"], body.locked)
    db.update_timetable_locks(user.college_id, version, kept)
    return {"version": version, "locked": kept}


@router.post("/timetables/{version}/restore", status_code=status.HTTP_201_CREATED)
def restore(version: int, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    """Make an older version the latest again (as a new version, so nothing is lost)."""
    base, data, current = current_base(version, user, db)
    new_version = save_checked(user, db, data, current, base["entries"], base.get("locked", []), solver_status="restored", restored_from=version)
    return {"version": new_version, "message": f"Timetable v{version} restored as v{new_version}."}


@router.post("/timetables/{version}/publish")
def publish(version: int, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    """Make this version the official timetable that teachers see. Only an up-to-date version can be published."""
    current_base(version, user, db)
    db.set_published(user.college_id, version)
    return {"published": db.published(user.college_id), "message": f"Timetable v{version} is published. Teachers now see this version."}


@router.delete("/published")
def unpublish(user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    db.set_published(user.college_id, None)
    return {"published": None, "message": "Not published any more. Teachers see no timetable until you publish one."}


@router.delete("/timetables/{version}")
def delete_version(version: int, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    if (db.published(user.college_id) or {}).get("version") == version:
        raise HTTPException(409, f"Timetable v{version} is the published one, so teachers are using it. Publish another version first.")
    if not db.delete_timetable(user.college_id, version):
        raise HTTPException(404, f"There's no timetable v{version}.")
    return {"deleted": version}


@router.post("/timetables/{version}/check")
def check(version: int, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    """Re-check a saved timetable against the college's current data (it may have changed since)."""
    timetable = db.get_timetable(user.college_id, version)
    if timetable is None:
        raise HTTPException(404, f"There's no timetable v{version}.")
    data, current = own_data(user, db)
    problems = validate(data, timetable["entries"])
    return {"version": version, "checked_against": current, "clashes": len(problems), "problems": problems}
