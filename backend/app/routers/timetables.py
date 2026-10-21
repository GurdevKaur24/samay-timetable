"""Pre-check, generation and saved timetables for the signed-in user's own college."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from solver.validator import validate

from ..auth import CurrentUser, current_user, get_db
from ..db import Database
from ..services.precheck import precheck

router = APIRouter(prefix="/api", tags=["timetables"])


def own_data(user: CurrentUser, db: Database) -> tuple[dict, int]:
    loaded = db.get_college_data_with_version(user.college_id)
    if loaded is None:
        raise HTTPException(404, "Your college's data couldn't be found.")
    return loaded


@router.get("/precheck")
def run_precheck(user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    data, _ = own_data(user, db)
    items = precheck(data)
    errors = sum(1 for i in items if i["level"] == "error")
    return {"ready": errors == 0, "errors": errors, "warnings": sum(1 for i in items if i["level"] == "warn"), "items": items}


@router.post("/timetables", status_code=status.HTTP_202_ACCEPTED)
def generate(request: Request, user: CurrentUser = Depends(current_user)):
    return request.app.state.jobs.start(user.college_id).public()


@router.get("/jobs/{job_id}")
def job_status(job_id: str, request: Request, user: CurrentUser = Depends(current_user)):
    job = request.app.state.jobs.get(user.college_id, job_id)
    if job is None:
        raise HTTPException(404, "That generation run wasn't found.")
    return job.public()


def with_freshness(timetable: dict, current_version: int) -> dict:
    timetable["out_of_date"] = timetable["built_from"] != current_version
    return timetable


@router.get("/timetables")
def list_versions(user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    current = db.get_data_version(user.college_id)
    return {"data_version": current, "timetables": [with_freshness(t, current) for t in db.list_timetables(user.college_id)]}


@router.get("/timetables/latest")
def latest(user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    return fetch(None, user, db)


@router.get("/timetables/{version}")
def one_version(version: int, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    return fetch(version, user, db)


def fetch(version: int | None, user: CurrentUser, db: Database) -> dict:
    timetable = db.get_timetable(user.college_id, version)
    if timetable is None:
        raise HTTPException(404, "No timetable yet. Generate one first." if version is None else f"There's no timetable v{version}.")
    return with_freshness(timetable, db.get_data_version(user.college_id))


@router.post("/timetables/{version}/check")
def check(version: int, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    """Re-check a saved timetable against the college's current data (it may have changed since)."""
    timetable = db.get_timetable(user.college_id, version)
    if timetable is None:
        raise HTTPException(404, f"There's no timetable v{version}.")
    data, current = own_data(user, db)
    problems = validate(data, timetable["entries"])
    return {"version": version, "checked_against": current, "clashes": len(problems), "problems": problems}
