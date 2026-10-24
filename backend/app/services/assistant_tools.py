"""What the AI scheduling assistant can look at and suggest, for one college's latest timetable.

Every tool is read-only. `propose_change` only checks a change with the clash checker and keeps it as a proposal;
the page shows it as a preview and nothing is saved until the coordinator applies it (through the normal revise
endpoint, which checks it again). Pure Python, so it can be tested without calling Claude.
"""

import copy
import json
from collections import defaultdict

from solver.college import build
from solver.validator import validate

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
