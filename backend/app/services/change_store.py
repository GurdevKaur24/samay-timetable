"""Saving changes made after publishing. A change "from now on" becomes a new published version (the moved class is
locked there, so making the timetable again keeps it); one-week changes are carried to a newly published version
when they still fit it."""

from solver.college import build
from solver.metrics import metrics
from solver.validator import validate

from ..db import Database
from . import changes
from .fingerprint import schedule_fingerprint


def plain(entries: list[dict]) -> list[dict]:
    return [{k: e[k] for k in ("assignment", "day", "period", "room")} for e in entries]


def lock_for(data: dict, assignment: str, day: str, start: int, room: str) -> dict:
    a = build(data).assignments[assignment]
    return {"assignment": assignment, "subject": a["subject"], "group": a["group"], "day": day, "start": start, "room": room}


def locks_still_in(entries: list[dict], locked: list[dict]) -> list[dict]:
    """Locks that still match a session's first period and room."""
    starts = {}
    for e in entries:
        key = (e["assignment"], e["day"])
        if key not in starts or e["period"] < starts[key][0]:
            starts[key] = (e["period"], e["room"])
    return [lk for lk in locked if starts.get((lk["assignment"], lk["day"])) == (lk["start"], lk["room"])]


class NotSaved(ValueError):
    def __init__(self, status: int, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.status, self.problems = status, problems or []


def publish_moved(db: Database, college_id: str, base: dict, entries: list[dict], *, moved: tuple[str, str, int, str] | None,
                  changed_by: str, tz: str) -> tuple[int, int]:
    """Save `entries` (the published version `base` with a class moved) as a new published version; returns
    (new version, one-week changes that no longer fit and were removed)."""
    loaded = db.get_college_data_with_version(college_id)
    if loaded is None:
        raise NotSaved(404, "Your college's data couldn't be found.")
    data, data_version = loaded
    if schedule_fingerprint(base["data"]) != schedule_fingerprint(data):
        raise NotSaved(409, "Your timetable coordinator is changing the college's data right now, so the timetable can only be "
                            "changed for one week. Try a change for this week only, or ask your coordinator.")
    problems = [p["message"] for p in validate(data, entries)]
    if problems:
        raise NotSaved(422, "The published timetable doesn't fit your college's latest data any more (for example, a teacher's "
                            "free times changed), so it can't be changed for good right now. Make a one-week change, or ask your "
                            "timetable coordinator to make the timetable again.", problems)
    locked = locks_still_in(entries, base.get("locked", []))
    if moved:
        locked = [lk for lk in locked if (lk["assignment"], lk["day"]) != moved[:2]] + [lock_for(data, *moved)]
    new_version = db.save_timetable(college_id, {
        "built_from": data_version, "seconds": 0, "entries": entries, "metrics": metrics(data, entries), "locked": locked,
        "data": data, "solver_status": "changed", "edited_from": base["version"], "changed_by": changed_by,
    })
    db.set_published(college_id, new_version)
    return new_version, carry_forward(db, college_id, base["version"], new_version, tz)


def carry_forward(db: Database, college_id: str, old_version: int | None, new_version: int, tz: str) -> int:
    """After a new version is published: keep each one-week change (from this week on) that still fits it, and remove
    the rest. Returns how many were removed."""
    if old_version is None or old_version == new_version:
        return 0
    timetable = db.get_timetable(college_id, new_version)
    current = db.get_college_data(college_id) or timetable["data"]
    data, entries = changes.with_current_availability(timetable["data"], current), plain(timetable["entries"])
    removed = 0
    for week in db.future_weeks(college_id, old_version, changes.week_start(changes.today(tz)).isoformat()):
        kept: list[dict] = []
        for ch in db.week_changes(college_id, old_version, week):
            before = changes.apply(entries, kept)
            fits = (changes.session_indexes(before, ch["assignment"], ch["from_day"], ch["from_start"])
                    and not changes.new_problems(data, before, changes.apply(before, [ch])))
            if fits:
                kept.append(ch)
                db.set_change_version(college_id, ch["id"], new_version)
            else:
                db.delete_change(college_id, ch["id"])
                removed += 1
    return removed
