"""A teacher's own pages: the published timetable of their college and the times they can't teach.
Teachers can't see or change anything else; the college still comes only from their session."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from ..auth import CurrentUser, teacher_only, get_db
from ..db import Database
from ..schema import CollegeData

router = APIRouter(prefix="/api/teacher", tags=["teacher"])


def for_viewers(data: dict) -> dict:
    """College data as people who only view timetables may see it: no teacher's free times or daily limits."""
    return {**data, "teachers": [{"id": t["id"], "name": t["name"], "dept": t["dept"]} for t in data.get("teachers", [])]}


def my_record(user: CurrentUser, data: dict) -> dict:
    me = next((t for t in data.get("teachers", []) if t["id"] == user.teacher_id), None)
    if me is None:
        raise HTTPException(404, "Your teacher record isn't in your college's data any more. Ask your timetable coordinator.")
    return me


def published_timetable(user: CurrentUser, db: Database) -> dict | None:
    info = db.published(user.college_id)
    timetable = db.get_timetable(user.college_id, info["version"]) if info else None
    if timetable is None:
        return None
    return {"version": timetable["version"], "published_at": info["published_at"], "data": for_viewers(timetable["data"]),
            "entries": [{k: e[k] for k in ("assignment", "day", "period", "room")} for e in timetable["entries"]]}


@router.get("")
def home(user: CurrentUser = Depends(teacher_only), db: Database = Depends(get_db)):
    data = db.get_college_data(user.college_id) or {}
    me = my_record(user, data)
    dept = next((d["name"] for d in data.get("departments", []) if d["id"] == me["dept"]), me["dept"])
    return {"me": {"id": me["id"], "name": me["name"], "dept": me["dept"], "dept_name": dept, "unavailable": me.get("unavailable", [])},
            "scheme": data["scheme"], "published": published_timetable(user, db)}


class Unavailable(BaseModel):
    unavailable: list[tuple[str, int]]


@router.put("/unavailable")
def set_unavailable(body: Unavailable, user: CurrentUser = Depends(teacher_only), db: Database = Depends(get_db)):
    """Save the periods this teacher can't teach. The next generated timetable respects them."""
    wanted = sorted(set(body.unavailable))

    def change(data: dict) -> dict:  # raising here stops the save
        my_record(user, data)
        days, periods = data["scheme"]["days"], len(data["scheme"]["periods"])
        if any(d not in days or not 1 <= p <= periods for d, p in wanted):
            raise HTTPException(422, "Some of those periods aren't in your college's week. Reload the page and try again.")
        teachers = [{**t, "unavailable": [list(x) for x in wanted]} if t["id"] == user.teacher_id else t for t in data["teachers"]]
        try:
            return CollegeData.model_validate({**data, "teachers": teachers}).model_dump(mode="json", exclude_none=True)
        except ValidationError as e:
            raise HTTPException(422, e.errors()[0]["msg"].removeprefix("Value error, "))

    if db.update_college_data(user.college_id, change) is None:
        raise HTTPException(409, "Your college's data is being changed right now. Try again in a moment.")

    # Classes in the published timetable that now fall on a time this teacher can't teach.
    clashes = []
    published = published_timetable(user, db)
    if published:
        mine = {a["id"] for a in published["data"]["assignments"] if a["teacher"] == user.teacher_id}
        clashes = sorted({(e["day"], e["period"]) for e in published["entries"] if e["assignment"] in mine} & set(wanted))
    message = "Saved. The next timetable your coordinator generates will keep these periods free."
    if clashes:
        message += (f" You have {len(clashes)} class(es) at those times in the published timetable, so it will change "
                    "once your coordinator generates and publishes again.")
    return {"unavailable": wanted, "clashes_with_published": clashes, "message": message}
