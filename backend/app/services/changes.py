"""Changes to the published timetable after it is published: a class moved or cancelled.

A change is either for **one week only** (a date's class moved to another free time that week, or cancelled that day;
the usual timetable comes back by itself afterwards) or **from now on** (saved as a new published version, until another
change). The clash checker judges every change: a change is refused if it adds any problem. Who may change what:
coordinators any class, heads of department their own department's classes, teachers only their own classes.
Pure Python (no FastAPI), so it can be tested on its own.
"""

import copy
import datetime as dt
from zoneinfo import ZoneInfo

from solver.college import build
from solver.validator import validate

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ---- dates -----------------------------------------------------------------------------------------------------
def today(tz: str) -> dt.date:
    return dt.datetime.now(ZoneInfo(tz)).date()


def week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def weekday_index(day: str) -> int | None:
    """A college's day name (Mon, Tuesday, ...) as 0 = Monday."""
    key = day.strip().lower()[:3]
    return WEEKDAYS.index(key) if key in WEEKDAYS else None


def week_dates(days: list[str], start: dt.date) -> dict[str, str]:
    """Each working day of the week that starts on `start` (a Monday), as an ISO date."""
    out = {}
    for d in days:
        i = weekday_index(d)
        if i is not None:
            out[d] = (start + dt.timedelta(days=i)).isoformat()
    return out


def day_of(days: list[str], date: dt.date) -> str | None:
    """The college's name for a date's weekday, or None if the college doesn't work that day."""
    return next((d for d in days if weekday_index(d) == date.weekday()), None)


# ---- applying one week's changes ---------------------------------------------------------------------------------
def session_indexes(entries: list[dict], assignment: str, day: str, start: int) -> list[int]:
    """The entries of one class session: the back-to-back periods of `assignment` on `day` from `start`."""
    at = {e["period"]: i for i, e in enumerate(entries)
          if e["assignment"] == assignment and e["day"] == day and not e.get("cancelled")}
    out, p = [], start
    while p in at:
        out.append(at[p])
        p += 1
    return out


def apply(entries: list[dict], changes: list[dict]) -> list[dict]:
    """One week's timetable: the published entries with that week's changes. A cancelled session stays in the list,
    marked `cancelled` (it takes no slot); a moved one is marked with where it was. Changes that no longer match
    the timetable are skipped."""
    out = [dict(e) for e in entries]
    for ch in sorted(changes, key=lambda x: x["id"]):
        idxs = session_indexes(out, ch["assignment"], ch["from_day"], ch["from_start"])
        if not idxs:
            continue
        for n, i in enumerate(idxs):
            if ch["kind"] == "cancel":
                out[i].update(cancelled=True, change=ch["id"])
            else:
                out[i].update(day=ch["to_day"], period=ch["to_start"] + n, room=ch["to_room"], change=ch["id"],
                              moved_from=[ch["from_day"], ch["from_start"] + n])
    return out


def held(entries: list[dict]) -> list[dict]:
    """Only the classes that take place (for the clash checker)."""
    return [{k: e[k] for k in ("assignment", "day", "period", "room")} for e in entries if not e.get("cancelled")]


def with_current_availability(version_data: dict, current: dict) -> dict:
    """The data a version was built from, with teachers' up-to-date unavailable periods (they may have changed)."""
    now = {t["id"]: t.get("unavailable", []) for t in current.get("teachers", [])}
    return {**version_data, "teachers": [{**t, "unavailable": now.get(t["id"], t.get("unavailable", []))} for t in version_data["teachers"]]}


def new_problems(data: dict, before: list[dict], after: list[dict]) -> list[str]:
    """Problems the change adds. A cancelled class is allowed to have fewer periods that week."""
    c = build(data)
    cancelled = {c.describe(e["assignment"]) for e in after if e.get("cancelled")}

    def problems(entries):
        return {p["message"] for p in validate(data, held(entries))
                if not (p["rule"] == "hours" and any(p["message"].startswith(d) for d in cancelled))}

    return sorted(problems(after) - problems(before))


# ---- who may change what ---------------------------------------------------------------------------------------
def may_change(role: str, teacher_id: str | None, dept_id: str | None, data: dict, assignment: str) -> bool:
    c = build(data)
    a = c.assignments.get(assignment)
    if a is None:
        return False
    if role == "coordinator":
        return True
    if role == "teacher":
        return bool(teacher_id) and a["teacher"] == teacher_id
    if role == "hod" and dept_id:
        depts = {s["id"]: s["dept"] for s in data.get("sections", [])}
        sections = c.sections_of(assignment)
        return bool(sections) and all(depts.get(s) == dept_id for s in sections)
    return False


def describe_change(data: dict, ch: dict) -> str:
    c = build(data)
    what = c.describe(ch["assignment"]) if ch["assignment"] in c.assignments else ch["assignment"]
    frm = c.slot_label(ch["from_day"], ch["from_start"])
    when = f" on {ch['date']}" if ch.get("date") else ""
    if ch["kind"] == "cancel":
        return f"{what}: cancelled{when} ({frm})."
    to = f"{c.slot_label(ch['to_day'], ch['to_start'])} in {ch['to_room']}"
    return f"{what}: {frm} → {to}{' for that week only' if ch.get('scope') == 'once' else ' from now on'}."


# ---- checking a change ------------------------------------------------------------------------------------------
class ChangeError(ValueError):
    """A change that can't be made, with a plain-English reason (and the clash checker's problems, if any)."""

    def __init__(self, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.problems = problems or []


def check(request: dict, *, version_entries: list[dict], version_data: dict, current_data: dict, week_changes: list[dict],
          role: str, teacher_id: str | None, dept_id: str | None, tz: str) -> dict:
    """Check one requested change; returns the change record to store (without id) or raises ChangeError.

    request: {action: move|cancel, scope: once|always, assignment, date (ISO, of the class), from_start,
              to_date (ISO, moves within that week), to_start, to_room}
    """
    data = with_current_availability(version_data, current_data)
    c = build(data)
    aid, action, scope = request.get("assignment", ""), request.get("action"), request.get("scope", "once")
    if action not in ("move", "cancel") or scope not in ("once", "always"):
        raise ChangeError("Choose to move or cancel a class, for one week or from now on.")
    if aid not in c.assignments:
        raise ChangeError("That class isn't in the published timetable.")
    if not may_change(role, teacher_id, dept_id, data, aid):
        raise ChangeError("You can only change your own classes." if role == "teacher"
                          else "You can only change your own department's classes." if role == "hod"
                          else "You can't change classes.")
    if action == "cancel" and scope == "always":
        raise ChangeError("A class can only be cancelled for one day. To stop it for good, ask your timetable coordinator.")
    try:
        date = dt.date.fromisoformat(request.get("date", ""))
    except ValueError:
        raise ChangeError("Give the date of the class, like 2026-10-28.")
    if scope == "once" and date < today(tz):
        raise ChangeError("That date has already passed.")
    from_day = day_of(c.days, date)
    if from_day is None:
        raise ChangeError(f"{date.isoformat()} isn't a working day at your college.")
    start = request.get("from_start")
    week = week_start(date)
    before = apply(version_entries, week_changes) if scope == "once" else [dict(e) for e in version_entries]
    idxs = session_indexes(before, aid, from_day, start) if isinstance(start, int) else []
    if not idxs:
        raise ChangeError(f"{c.describe(aid)} isn't at {c.slot_label(from_day, start) if isinstance(start, int) else 'that time'}"
                          f"{' that week' if scope == 'once' else ''}.")
    record = {"kind": action, "scope": scope, "assignment": aid, "date": date.isoformat() if scope == "once" else None,
              "week": week.isoformat() if scope == "once" else None, "from_day": from_day, "from_start": start,
              "to_day": None, "to_start": None, "to_room": None}
    if action == "move":
        to_start, to_room = request.get("to_start"), request.get("to_room", "")
        try:
            to_date = dt.date.fromisoformat(request.get("to_date") or date.isoformat())
        except ValueError:
            raise ChangeError("Give the new date like 2026-10-29.")
        if scope == "once" and week_start(to_date) != week:
            raise ChangeError("A one-week change has to stay in the same week (Monday to the week's last day).")
        if scope == "once" and to_date < today(tz):
            raise ChangeError("That new date has already passed.")
        to_day = day_of(c.days, to_date)
        if to_day is None:
            raise ChangeError(f"{to_date.isoformat()} isn't a working day at your college.")
        if to_room not in c.rooms:
            raise ChangeError(f"There's no room {to_room}.")
        if not isinstance(to_start, int) or to_start not in c.periods or to_start + len(idxs) - 1 not in c.periods:
            raise ChangeError(f"That class is {len(idxs)} period(s) long, so it can't start there.")
        if (to_day, to_start, to_room) == (from_day, start, before[idxs[0]]["room"]):
            raise ChangeError("That is where the class already is.")
        record.update(to_day=to_day, to_start=to_start, to_room=to_room, to_date=to_date.isoformat() if scope == "once" else None)
    record["from_room"] = before[idxs[0]]["room"]
    after = apply(before, [{**record, "id": 10**9}])
    problems = new_problems(data, before, after)
    if problems:
        raise ChangeError(f"That change wasn't made: it would cause {len(problems)} problem(s).", problems)
    record["entries_after"] = held(after)
    return record


def suggest(version_entries: list[dict], version_data: dict, current_data: dict, week_changes: list[dict], *, assignment: str,
            day: str, start: int, scope: str, days: list[str] | None = None, limit: int = 12) -> list[dict]:
    """Times (day, start period, room) where one session could go without adding a problem."""
    data = with_current_availability(version_data, current_data)
    c = build(data)
    before = apply(version_entries, week_changes) if scope == "once" else [dict(e) for e in version_entries]
    idxs = session_indexes(before, assignment, day, start)
    if not idxs:
        return []
    group = c.groups[c.assignments[assignment]["group"]]
    rooms = sorted((r for r in c.rooms.values() if r["type"] == c.room_type(assignment) and r["capacity"] >= group.strength),
                   key=lambda r: (r["id"] != before[idxs[0]]["room"], r["capacity"]))
    found = []
    for to_day in days or c.days:
        for to_start in c.periods:
            if (to_day, to_start) == (day, start) or to_start + len(idxs) - 1 not in c.periods:
                continue
            for room in rooms:
                trial = copy.deepcopy(before)
                for n, i in enumerate(idxs):
                    trial[i].update(day=to_day, period=to_start + n, room=room["id"])
                if not new_problems(data, before, trial):
                    found.append({"day": to_day, "start": to_start, "start_label": c.period_labels[to_start], "room": room["id"]})
                    break
            if len(found) >= limit:
                return found
    return found
