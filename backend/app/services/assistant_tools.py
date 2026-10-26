"""What the AI scheduling assistant can look at and suggest, for one college's latest timetable.

Every tool is read-only. `propose_change` only checks a change with the clash checker and keeps it as a proposal;
the page shows it as a preview and nothing is saved until the coordinator applies it (through the normal revise
endpoint, which checks it again). Pure Python, so it can be tested without calling Claude.
"""

import copy
import datetime as dt
import json
from collections import defaultdict
from zoneinfo import ZoneInfo

from solver.college import build
from solver.validator import validate

from . import changes
from .fingerprint import schedule_fingerprint

MAX_FREE_SLOTS = 12


def as_text(value) -> str:
    return json.dumps(value, ensure_ascii=False)


class SchedulingTools:
    def __init__(self, data: dict, timetable: dict | None):
        self.data = data
        self.c = build(data)
        self.timetable = timetable
        self.current = timetable is not None and schedule_fingerprint(timetable["data"]) == schedule_fingerprint(data)
        self.entries = [{k: e[k] for k in ("assignment", "day", "period", "room")} for e in timetable["entries"]] if self.current else []
        self.proposal: dict | None = None

    # ---- helpers ------------------------------------------------------------------------------------------
    def _status(self) -> str:
        if self.timetable is None:
            return "No timetable has been generated yet."
        if not self.current:
            return (f"Timetable v{self.timetable['version']} was made before the latest data changes, so it is out of date. "
                    "The coordinator needs to generate again before classes can be moved.")
        return f"Showing timetable v{self.timetable['version']} (the latest)."

    def _sessions(self, entries: list[dict]) -> dict[tuple[str, str], dict]:
        """(assignment, day) -> {start, periods, room}"""
        out: dict[tuple[str, str], dict] = {}
        for e in sorted(entries, key=lambda e: e["period"]):
            s = out.setdefault((e["assignment"], e["day"]), {"start": e["period"], "periods": 0, "room": e["room"]})
            s["periods"] += 1
        return out

    def _describe_session(self, aid: str, day: str, s: dict) -> dict:
        a, c = self.c.assignments[aid], self.c
        subject = c.subjects[a["subject"]]
        return {"assignment": aid, "day": day, "start": c.period_labels[s["start"]], "start_period": s["start"], "periods": s["periods"],
                "subject": subject["name"], "kind": subject["kind"], "taught_to": c.group_label(a["group"]),
                "teacher": c.teachers[a["teacher"]]["name"], "teacher_id": a["teacher"], "room": s["room"]}

    def _period(self, value: int | str) -> int | None:
        if isinstance(value, int) or str(value).isdigit():
            p = int(value)
            return p if p in self.c.periods else None
        found = [p for p, label in self.c.period_labels.items() if label.lower() == str(value).strip().lower()]
        return found[0] if found else None

    def _moved(self, entries: list[dict], aid: str, day: str, to_day: str, to_start: int, to_room: str) -> list[dict] | str:
        """Entries with one class session moved; or a plain reason it can't be moved like that."""
        idxs = sorted((i for i, e in enumerate(entries) if e["assignment"] == aid and e["day"] == day), key=lambda i: entries[i]["period"])
        if not idxs:
            return f"There is no class {aid} on {day}."
        if to_day not in self.c.days:
            return f"{to_day} isn't a working day. Days: {', '.join(self.c.days)}."
        if to_room not in self.c.rooms:
            return f"There is no room {to_room}."
        last = to_start + len(idxs) - 1
        if to_start not in self.c.periods or last not in self.c.periods:
            return f"That class is {len(idxs)} period(s) long, so it can't start at {self.c.period_labels.get(to_start, to_start)}."
        out = copy.deepcopy(entries)
        for n, i in enumerate(idxs):
            out[i].update(day=to_day, period=to_start + n, room=to_room)
        return out

    # ---- tools ----------------------------------------------------------------------------------------------
    def overview(self) -> str:
        c = self.c
        return as_text({
            "status": self._status(),
            "days": c.days,
            "periods": [{"period": p, "label": c.period_labels[p], "start": s["start"], "end": s["end"]} for p, s in zip(c.periods, self.data["scheme"]["periods"])],
            "breaks_after_period": sorted(c.breaks_after),
            "departments": [{"id": d["id"], "name": d["name"]} for d in self.data["departments"]],
            "sections": [{"id": s["id"], "dept": s["dept"], "students": s["strength"], "lab_groups": c.subsections[s["id"]]} for s in self.data["sections"]],
            "teachers": [{"id": t["id"], "name": t["name"], "dept": t["dept"]} for t in self.data["teachers"]],
            "rooms": [{"id": r["id"], "type": r["type"], "seats": r["capacity"]} for r in self.data["rooms"]],
            "subjects": [{"id": s["id"], "name": s["name"], "short": s["short"], "kind": s["kind"]} for s in self.data["subjects"]],
        })

    def find_clashes(self) -> str:
        if not self.entries:
            return self._status()
        problems = [p["message"] for p in validate(self.data, self.entries)]
        return as_text({"status": self._status(), "clashes": len(problems), "problems": problems})

    def show_timetable(self, kind: str, key: str) -> str:
        if not self.entries:
            return self._status()
        c = self.c
        if kind == "section":
            if key not in c.groups or c.groups[key].is_sub:
                return f"No section {key}. Sections: {', '.join(s['id'] for s in self.data['sections'])}."
            match = lambda a: c.groups[a["group"]].section == key  # noqa: E731
        elif kind == "teacher":
            tid = key if key in c.teachers else next((t for t, v in c.teachers.items() if v["name"].lower() == key.lower()), None)
            if tid is None:
                return f"No teacher {key}. Use a teacher id or exact name from the overview."
            match = lambda a: a["teacher"] == tid  # noqa: E731
        elif kind == "room":
            if key not in c.rooms:
                return f"No room {key}."
            match = None
        else:
            return "kind must be section, teacher or room."
        rows = []
        for (aid, day), s in self._sessions(self.entries).items():
            if (match is None and s["room"] == key) or (match is not None and match(c.assignments[aid])):
                rows.append(self._describe_session(aid, day, s))
        rows.sort(key=lambda r: (c.days.index(r["day"]), r["start_period"]))
        return as_text({"status": self._status(), "classes": rows})

    def find_free_slots(self, assignment: str, day: str) -> str:
        """Where one class session could move with 0 clashes (every rule checked)."""
        if not self.entries:
            return self._status()
        session = self._sessions(self.entries).get((assignment, day))
        if session is None:
            return f"There is no class {assignment} on {day}. Use show_timetable to find the class and its day."
        c, a = self.c, self.c.assignments[assignment]
        group = c.groups[a["group"]]
        rooms = sorted((r for r in c.rooms.values() if r["type"] == c.room_type(assignment) and r["capacity"] >= group.strength),
                       key=lambda r: r["capacity"])
        found = []
        for to_day in c.days:
            for start in c.periods:
                if (to_day, start) == (day, session["start"]):
                    continue
                for room in rooms:
                    moved = self._moved(self.entries, assignment, day, to_day, start, room["id"])
                    if isinstance(moved, list) and not validate(self.data, moved):
                        found.append({"day": to_day, "start": c.period_labels[start], "start_period": start, "room": room["id"]})
                        break
                if len(found) >= MAX_FREE_SLOTS:
                    break
            if len(found) >= MAX_FREE_SLOTS:
                break
        return as_text({"class": self._describe_session(assignment, day, session), "free_slots": found,
                        "note": "Each slot keeps 0 clashes if only this class moves." if found else "No slot works without moving another class too."})

    def find_free_rooms(self, day: str, period: int | str) -> str:
        p = self._period(period)
        if day not in self.c.days or p is None:
            return "Use a working day and a period number or label from the overview."
        busy = {e["room"] for e in self.entries if e["day"] == day and e["period"] == p}
        free = [{"id": r["id"], "type": r["type"], "seats": r["capacity"]} for r in self.data["rooms"] if r["id"] not in busy]
        return as_text({"day": day, "period": self.c.period_labels[p], "free_rooms": free})

    def teacher_load(self, teacher: str) -> str:
        c = self.c
        tid = teacher if teacher in c.teachers else next((t for t, v in c.teachers.items() if v["name"].lower() == teacher.lower()), None)
        if tid is None:
            return f"No teacher {teacher}."
        per_day = defaultdict(int)
        for e in self.entries:
            if c.assignments[e["assignment"]]["teacher"] == tid:
                per_day[e["day"]] += 1
        t = c.teachers[tid]
        return as_text({"teacher": t["name"], "dept": t["dept"], "max_periods_a_day": t["max_per_day"],
                        "cannot_teach": [f"{d} {c.period_labels.get(p, p)}" for d, p in sorted(c.unavailable[tid])],
                        "periods_by_day": {d: per_day.get(d, 0) for d in c.days}, "periods_a_week": sum(per_day.values()),
                        "status": self._status()})

    def propose_change(self, moves: list[dict], summary: str) -> str:
        """Check moves together; keep them as the proposal if they leave 0 clashes. Nothing is saved."""
        if not self.entries:
            return self._status()
        if not moves:
            return "Give at least one move."
        entries = self.entries
        for m in moves:
            start = self._period(m.get("to_start", ""))
            if start is None:
                return f"Unknown start period {m.get('to_start')!r}."
            moved = self._moved(entries, m.get("assignment", ""), m.get("day", ""), m.get("to_day", ""), start, m.get("to_room", ""))
            if isinstance(moved, str):
                return f"Not proposed: {moved}"
            entries = moved
        problems = [p["message"] for p in validate(self.data, entries)]
        if problems:
            return as_text({"proposed": False, "reason": "This change would cause clashes, so it can't be offered.", "problems": problems})
        changes = [{"assignment": old["assignment"], "from_day": old["day"], "from_period": old["period"],
                    "day": new["day"], "period": new["period"], "room": new["room"]}
                   for old, new in zip(self.entries, entries) if old != new]
        if not changes:
            return "Those moves don't change anything."
        self.proposal = {"summary": summary.strip()[:400], "changes": changes, "version": self.timetable["version"]}
        return as_text({"proposed": True, "clashes_after": 0, "changed_periods": len(changes),
                        "note": "The coordinator now sees this as a preview on the timetable. It is saved only if they click Apply."})


class WeekTools:
    """What the assistant can look at for a head of department, a teacher or a student: the published timetable, one
    week at a time with that week's changes. Heads of department and teachers can also find free times and propose a
    change to a class they're allowed to change; the page shows it and the person applies it (POST /api/changes, which
    checks it again). Nobody's free times or daily limits are ever shown. `week_changes(week)` reads one week's changes."""

    def __init__(self, *, college_name: str, base: dict | None, current_data: dict, week_changes, role: str,
                 teacher_id: str | None = None, dept_id: str | None = None, person: str = "", tz: str = "Asia/Kolkata"):
        self.role, self.person, self.college_name = role, person, college_name
        self.base, self.current_data, self.week_changes = base, current_data, week_changes
        self.teacher_id, self.dept_id, self.tz = teacher_id, dept_id, tz
        self.data = base["data"] if base else current_data
        self.c = build(self.data)
        self.entries = [{k: e[k] for k in ("assignment", "day", "period", "room")} for e in base["entries"]] if base else []
        self.proposal: dict | None = None

    # ---- helpers ------------------------------------------------------------------------------------------------
    def _date(self, value: str | None) -> dt.date | None:
        try:
            return dt.date.fromisoformat(value) if value else changes.today(self.tz)
        except ValueError:
            return None

    def _week(self, date: dt.date) -> tuple[dt.date, list[dict], list[dict]]:
        start = changes.week_start(date)
        found = self.week_changes(start.isoformat()) if self.base else []
        return start, found, changes.apply(self.entries, found)

    def _teacher(self, key: str) -> str | None:
        c = self.c
        return key if key in c.teachers else next((t for t, v in c.teachers.items() if v["name"].lower() == key.strip().lower()), None)

    def _staff_only(self) -> str | None:
        if self.role == "student":
            return "Students can't change the timetable."
        if not self.base:
            return "No timetable has been published yet."
        return None

    # ---- tools --------------------------------------------------------------------------------------------------
    def today(self) -> str:
        now = dt.datetime.now(ZoneInfo(self.tz))
        day = changes.day_of(self.c.days, now.date())
        hhmm, current = now.strftime("%H:%M"), "no class period right now"
        for p, s in zip(self.c.periods, self.data["scheme"]["periods"]):
            if s["start"] <= hhmm < s["end"]:
                current = f"{self.c.period_labels[p]} (period {p}, {s['start']}–{s['end']})"
        you = {"teacher": f"the teacher {self.c.teachers.get(self.teacher_id, {}).get('name', self.person)} (teacher id {self.teacher_id})",
               "hod": f"the head of department {self.dept_id}", "student": "a student"}.get(self.role, self.role)
        return as_text({"date": now.date().isoformat(), "time": hhmm, "day": day or "not a working day", "now": current,
                        "this_week": changes.week_dates(self.c.days, changes.week_start(now.date())), "you_are": you})

    def overview(self) -> str:
        c = self.c
        return as_text({
            "published": f"version {self.base['version']}" if self.base else "nothing published yet",
            "days": c.days,
            "periods": [{"period": p, "label": c.period_labels[p], "start": s["start"], "end": s["end"]} for p, s in zip(c.periods, self.data["scheme"]["periods"])],
            "breaks_after_period": sorted(c.breaks_after),
            "departments": [{"id": d["id"], "name": d["name"]} for d in self.data["departments"]],
            "sections": [{"id": s["id"], "dept": s["dept"], "lab_groups": [c.groups[g].label for g in c.subsections[s["id"]]]} for s in self.data["sections"]],
            "teachers": [{"id": t["id"], "name": t["name"], "dept": t["dept"]} for t in self.data["teachers"]],
            "rooms": [{"id": r["id"], "type": r["type"], "seats": r["capacity"]} for r in self.data["rooms"]],
            "subjects": [{"id": s["id"], "name": s["name"], "short": s["short"], "kind": s["kind"]} for s in self.data["subjects"]],
        })

    def show_timetable(self, kind: str, key: str, date: str | None = None) -> str:
        if not self.base:
            return "No timetable has been published yet."
        when = self._date(date)
        if when is None:
            return "Give the date like 2026-10-28, or leave it out for this week."
        c = self.c
        if kind == "section":
            if key not in c.groups or c.groups[key].is_sub:
                return f"No section {key}. Sections: {', '.join(s['id'] for s in self.data['sections'])}."
            match = lambda a: key in c.sections_of(a["id"])  # noqa: E731
        elif kind == "teacher":
            tid = self._teacher(key)
            if tid is None:
                return f"No teacher {key}. Use a teacher id or exact name from the overview."
            match = lambda a: a["teacher"] == tid  # noqa: E731
        elif kind == "room":
            if key not in c.rooms:
                return f"No room {key}."
            match = None
        else:
            return "kind must be section, teacher or room."
        start, _, week = self._week(when)
        dates = changes.week_dates(c.days, start)
        rows: list[dict] = []
        for e in sorted(week, key=lambda e: (c.days.index(e["day"]), e["period"])):
            a = c.assignments.get(e["assignment"])
            if a is None or (match is None and e["room"] != key) or (match is not None and not match(a)):
                continue
            last = rows[-1] if rows else None
            same = last and (last["class_id"], last["day"], last["_change"], last["_cancelled"]) == (e["assignment"], e["day"], e.get("change"), bool(e.get("cancelled")))
            if same and last["_end"] + 1 == e["period"]:
                last["periods"] += 1
                last["_end"] = e["period"]
                continue
            subject = c.subjects[a["subject"]]
            status = ("cancelled this week" if e.get("cancelled") else
                      f"moved here for this week only (usually {c.slot_label(*e['moved_from'])})" if e.get("moved_from") else "as usual")
            rows.append({"day": e["day"], "date": dates.get(e["day"]), "start": c.period_labels[e["period"]], "start_period": e["period"],
                         "periods": 1, "subject": subject["name"], "kind": subject["kind"], "taught_to": c.group_label(a["group"]),
                         "teacher": c.teachers[a["teacher"]]["name"], "room": e["room"], "class_id": e["assignment"], "status": status,
                         "_end": e["period"], "_change": e.get("change"), "_cancelled": bool(e.get("cancelled"))})
        for r in rows:
            for k in ("_end", "_change", "_cancelled"):
                r.pop(k)
        return as_text({"week_of": start.isoformat(), "classes": rows})

    def find_free_times(self, class_id: str, date: str, start_period: int, scope: str = "once") -> str:
        if refused := self._staff_only():
            return refused
        if not changes.may_change(self.role, self.teacher_id, self.dept_id, self.data, class_id):
            return "You can only change your own classes." if self.role == "teacher" else "You can only change your own department's classes."
        when = self._date(date)
        if when is None:
            return "Give the date of the class like 2026-10-28."
        start, found, _ = self._week(when)
        dates, today = changes.week_dates(self.c.days, start), changes.today(self.tz).isoformat()
        days = [d for d in self.c.days if scope == "always" or (dates.get(d) or "") >= today]
        slots = changes.suggest(self.entries, self.data, self.current_data, found if scope == "once" else [], assignment=class_id,
                                day=changes.day_of(self.c.days, when) or "", start=start_period, scope=scope, days=days)
        for s in slots:
            s["date"] = dates.get(s["day"]) if scope == "once" else None
        return as_text({"free_times": slots, "note": "Each keeps 0 clashes if only this class moves." if slots else "No free time found."})

    def propose_change(self, action: str, scope: str, class_id: str, date: str, from_start: int, summary: str,
                       to_date: str | None = None, to_start: int | None = None, to_room: str | None = None) -> str:
        if refused := self._staff_only():
            return refused
        request = {"action": action, "scope": scope, "assignment": class_id, "date": date, "from_start": from_start,
                   "to_date": to_date, "to_start": to_start, "to_room": to_room}
        when = self._date(date)
        found = self._week(when)[1] if when and scope == "once" else []
        try:
            record = changes.check(request, version_entries=self.entries, version_data=self.data, current_data=self.current_data,
                                   week_changes=found, role=self.role, teacher_id=self.teacher_id, dept_id=self.dept_id, tz=self.tz)
        except changes.ChangeError as e:
            return as_text({"proposed": False, "reason": str(e), "problems": e.problems})
        described = changes.describe_change(self.data, record)
        self.proposal = {"kind": "change", "request": request, "summary": summary.strip()[:400] or described, "detail": described}
        return as_text({"proposed": True, "change": described, "note": "The person now sees this with an Apply button. Nothing changes until they click it."})
