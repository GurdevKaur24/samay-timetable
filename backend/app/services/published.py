"""The published timetable: the version a college's teachers and heads of department see."""

from ..db import Database


def for_viewers(data: dict) -> dict:
    """College data as people who only view timetables may see it: no teacher's free times or daily limits."""
    return {**data, "teachers": [{"id": t["id"], "name": t["name"], "dept": t["dept"]} for t in data.get("teachers", [])]}


def published_timetable(college_id: str, db: Database) -> dict | None:
    """The college's published timetable as viewers (teachers, heads of department) see it, or None."""
    info = db.published(college_id)
    timetable = db.get_timetable(college_id, info["version"]) if info else None
    if timetable is None:
        return None
    return {"version": timetable["version"], "published_at": info["published_at"], "data": for_viewers(timetable["data"]),
            "entries": [{k: e[k] for k in ("assignment", "day", "period", "room")} for e in timetable["entries"]]}
