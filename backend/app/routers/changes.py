"""Changing the published timetable: a class moved or cancelled for one week, or moved from now on.

Coordinators may change any class, heads of department their own department's classes, teachers only their own.
Every change is checked with the clash checker and applies at once; coordinators see all changes and can undo them,
others see and undo their own. The college comes only from the signed-in user."""

import datetime as dt
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from .. import config
from ..auth import CurrentUser, current_user, get_db
from ..db import Database
from ..services import changes
from ..services.change_store import NotSaved, plain, publish_moved
from ..services.published import public_change

router = APIRouter(prefix="/api", tags=["changes"])


def staff(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.role == "coordinator" or (user.role == "hod" and user.dept_id) or (user.role == "teacher" and user.teacher_id):
        return user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't change the timetable.")


def tz(request: Request) -> str:
    return getattr(request.app.state, "timezone", config.TIMEZONE)


def published_base(college_id: str, db: Database) -> dict:
    info = db.published(college_id)
    timetable = db.get_timetable(college_id, info["version"]) if info else None
    if timetable is None:
        raise HTTPException(404, "Nothing is published yet, so there's no timetable to change.")
    timetable.setdefault("locked", [])
    return timetable


class ChangeIn(BaseModel):
    action: Literal["move", "cancel"]
    scope: Literal["once", "always"] = "once"
    assignment: str = Field(min_length=1, max_length=120)
    date: str = Field(description="The date of the class, YYYY-MM-DD")
    from_start: int
    to_date: str | None = None
    to_start: int | None = None
    to_room: str | None = None


def week_of(date: str) -> str | None:
    try:
        return changes.week_start(dt.date.fromisoformat(date)).isoformat()
    except ValueError:
        return None


def dry_run(body: dict, user: CurrentUser, db: Database, zone: str) -> tuple[dict, dict, list[dict]]:
    """Check a change without saving it: (change record, published timetable, entries after the change)."""
    base = published_base(user.college_id, db)
    week = week_of(body.get("date", ""))
    week_changes = db.week_changes(user.college_id, base["version"], week) if week and body.get("scope", "once") == "once" else []
    try:
        record = changes.check(body, version_entries=plain(base["entries"]), version_data=base["data"],
                               current_data=db.get_college_data(user.college_id) or base["data"], week_changes=week_changes,
                               role=user.role, teacher_id=user.teacher_id, dept_id=user.dept_id, tz=zone)
    except changes.ChangeError as e:
        raise HTTPException(422, {"message": str(e), "problems": e.problems})
    return record, base, record.pop("entries_after")


@router.post("/changes", status_code=status.HTTP_201_CREATED)
def make_change(body: ChangeIn, request: Request, user: CurrentUser = Depends(staff), db: Database = Depends(get_db)):
    zone = tz(request)
    record, base, after = dry_run(body.model_dump(), user, db, zone)
    summary = changes.describe_change(base["data"], record)
    saved = {**record, "version": base["version"], "made_by": user.id, "made_by_name": user.name, "made_by_role": user.role, "summary": summary}
    if record["scope"] == "once":
        change_id = db.add_change(user.college_id, saved)
        when = "that day" if record["kind"] == "cancel" else "that week"
        return {"change": public_change({**saved, "id": change_id}, True),
                "message": f"Done. {summary} The usual timetable comes back by itself after {when}."}
    try:
        new_version, removed = publish_moved(db, user.college_id, base, after, tz=zone, changed_by=user.name,
                                             moved=(record["assignment"], record["to_day"], record["to_start"], record["to_room"]))
    except NotSaved as e:
        raise HTTPException(e.status, {"message": str(e), "problems": e.problems} if e.problems else str(e))
    change_id = db.add_change(user.college_id, {**saved, "new_version": new_version})
    note = f" {removed} one-week change(s) no longer fitted and were removed." if removed else ""
    return {"change": public_change({**saved, "id": change_id}, True), "version": new_version,
            "message": f"Done. {summary} Saved and published as timetable v{new_version}.{note}"}


@router.post("/changes/check")
def check_change(body: ChangeIn, request: Request, user: CurrentUser = Depends(staff), db: Database = Depends(get_db)):
    """Would this change work? Nothing is saved."""
    record, base, _ = dry_run(body.model_dump(), user, db, tz(request))
    return {"ok": True, "summary": changes.describe_change(base["data"], record)}


@router.get("/changes")
def list_changes(request: Request, user: CurrentUser = Depends(staff), db: Database = Depends(get_db)):
    """Coordinators: every change from this week on (and changes from now on in the last 30 days). Others: their own."""
    this_week = changes.week_start(changes.today(tz(request))).isoformat()
    rows = db.list_changes(user.college_id, this_week, time.time() - 30 * 24 * 3600)
    if user.role != "coordinator":
        rows = [r for r in rows if r["made_by"] == user.id]
    return {"changes": [{**public_change(r, True), "created_at": r["created_at"], "new_version": r["new_version"]} for r in rows]}


@router.delete("/changes/{change_id}")
def undo_change(change_id: int, request: Request, user: CurrentUser = Depends(staff), db: Database = Depends(get_db)):
    ch = db.get_change(user.college_id, change_id)
    if ch is None:
        raise HTTPException(404, "That change isn't there any more.")
    if user.role != "coordinator" and ch["made_by"] != user.id:
        raise HTTPException(403, "You can only undo your own changes.")
    if ch["scope"] == "once":
        db.delete_change(user.college_id, change_id)
        return {"undone": change_id, "message": f"Undone. {ch['summary']}"}
    base = published_base(user.college_id, db)
    entries = plain(base["entries"])
    idxs = changes.session_indexes(entries, ch["assignment"], ch["to_day"], ch["to_start"])
    if not idxs:
        raise HTTPException(409, "That class has been changed again since, so this can't be undone automatically. Move it back with a new change.")
    for n, i in enumerate(idxs):
        entries[i].update(day=ch["from_day"], period=ch["from_start"] + n, room=ch["from_room"] or entries[i]["room"])
    try:
        new_version, removed = publish_moved(db, user.college_id, base, entries, tz=tz(request), changed_by=user.name, moved=None)
    except NotSaved as e:
        raise HTTPException(e.status, {"message": "It can't be moved back: " + str(e), "problems": e.problems} if e.problems else str(e))
    db.delete_change(user.college_id, change_id)
    note = f" {removed} one-week change(s) no longer fitted and were removed." if removed else ""
    return {"undone": change_id, "version": new_version, "message": f"Undone and published as timetable v{new_version}.{note}"}
