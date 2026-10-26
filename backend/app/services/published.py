"""The published timetable: the version a college's teachers, heads of department and students see, and one week of
it with that week's one-week changes (a class moved or cancelled for that week only)."""

import datetime as dt

from ..db import Database
from . import changes


def for_viewers(data: dict) -> dict:
    """College data as people who only view timetables may see it: no teacher's free times or daily limits."""
    return {**data, "teachers": [{"id": t["id"], "name": t["name"], "dept": t["dept"]} for t in data.get("teachers", [])]}


def week_from(value: str | None) -> dt.date | None:
    """A date from a `?week=` query (any day of the week wanted), or None for this week."""
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def public_change(ch: dict, staff: bool) -> dict:
    keep = ["id", "kind", "scope", "assignment", "date", "from_day", "from_start", "to_date", "to_day", "to_start", "to_room", "summary"]
    return {k: ch.get(k) for k in keep + (["made_by_name", "made_by", "made_by_role"] if staff else [])}


def published_timetable(college_id: str, db: Database, *, tz: str = "Asia/Kolkata", week_of: dt.date | None = None,
                        staff: bool = False) -> dict | None:
    """The college's published timetable as viewers see it, or None. `week` is one week of it (this week by default)
    with that week's changes applied: moved classes carry `moved_from`, cancelled ones `cancelled`."""
    info = db.published(college_id)
    timetable = db.get_timetable(college_id, info["version"]) if info else None
    if timetable is None:
        return None
    entries = [{k: e[k] for k in ("assignment", "day", "period", "room")} for e in timetable["entries"]]
    today = changes.today(tz)
    start = changes.week_start(week_of or today)
    week_changes = db.week_changes(college_id, timetable["version"], start.isoformat())
    return {"version": timetable["version"], "published_at": info["published_at"], "data": for_viewers(timetable["data"]),
            "entries": entries,
            "week": {"start": start.isoformat(), "today": today.isoformat(), "dates": changes.week_dates(timetable["data"]["scheme"]["days"], start),
                     "changes": [public_change(ch, staff) for ch in week_changes], "entries": changes.apply(entries, week_changes)}}
