"""A teacher's own pages: the published timetable of their college and the times they can't teach.
Teachers can't see or change anything else; the college still comes only from their session."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from ..auth import CurrentUser, teacher_only, get_db
from ..db import Database
from ..schema import CollegeData
from ..services.published import published_timetable, week_from

router = APIRouter(prefix="/api/teacher", tags=["teacher"])


def my_record(user: CurrentUser, data: dict) -> dict:
    me = next((t for t in data.get("teachers", []) if t["id"] == user.teacher_id), None)
    if me is None:
        raise HTTPException(404, "Your teacher record isn't in your college's data any more. Ask your timetable coordinator.")
    return me


@router.get("")
def home(request: Request, week: str | None = None, user: CurrentUser = Depends(teacher_only), db: Database = Depends(get_db)):
    data = db.get_college_data(user.college_id) or {}
    me = my_record(user, data)
    dept = next((d["name"] for d in data.get("departments", []) if d["id"] == me["dept"]), me["dept"])
    return {"me": {"id": me["id"], "name": me["name"], "dept": me["dept"], "dept_name": dept, "unavailable": me.get("unavailable", [])},
            "scheme": data["scheme"], "published": published_timetable(user.college_id, db, tz=request.app.state.timezone, week_of=week_from(week), staff=True)}


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
    published = published_timetable(user.college_id, db)
    if published:
        mine = {a["id"] for a in published["data"]["assignments"] if a["teacher"] == user.teacher_id}
        clashes = sorted({(e["day"], e["period"]) for e in published["entries"] if e["assignment"] in mine} & set(wanted))
    message = "Saved. The next timetable your coordinator generates will keep these periods free."
    if clashes:
        message += (f" You have {len(clashes)} class(es) at those times in the published timetable, so it will change "
                    "once your coordinator generates and publishes again.")
    return {"unavailable": wanted, "clashes_with_published": clashes, "message": message}
