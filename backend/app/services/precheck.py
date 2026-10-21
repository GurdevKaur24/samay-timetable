"""Before generating: find data that would make a timetable impossible, in plain English.

Levels: "error" (must fix, generating will fail), "warn" (worth checking), "info" (good to know), "ok" (checked, fine).
"""

from collections import defaultdict

from pydantic import ValidationError

from solver.college import build

from ..schema import CollegeData

RANK = {"error": 0, "warn": 1, "info": 2, "ok": 3}


def type_name(t: str) -> str:
    return t.replace("_", " ").capitalize()


def precheck(data: dict) -> list[dict]:
    try:
        CollegeData.model_validate(data)
    except ValidationError as e:
        return [{"level": "error", "text": err["msg"].removeprefix("Value error, "), "fix": "data"} for err in e.errors()]

    c = build(data)
    days, slots = len(c.days), len(c.days) * len(c.periods)
    out: list[dict] = []

    load: dict[str, int] = defaultdict(int)
    for a in c.assignments.values():
        load[a["teacher"]] += a["periods"]
    for tid, t in c.teachers.items():
        cap = t["max_per_day"] * days - len(c.unavailable.get(tid, ()))
        if load[tid] > cap:
            out.append({"level": "error", "text": f"{t['name']} has {load[tid]} periods a week but can teach at most {cap}.", "fix": "teachers"})
        elif load[tid] > 0.6 * cap:
            out.append({"level": "warn", "text": f"{t['name']} has a heavy load: {load[tid]} of a possible {cap} periods a week.", "fix": "teachers"})

    for section, subs in c.subsections.items():
        whole = sum(a["periods"] for a in c.assignments.values() if a["group"] == section)
        labs = max((sum(a["periods"] for a in c.assignments.values() if a["group"] == g) for g in subs), default=0)
        need = whole + labs
        if need > slots:
            out.append({"level": "error", "text": f"{section} needs {need} periods but the week has only {slots}.", "fix": "sections"})
        else:
            out.append({"level": "ok", "text": f"{section}: {need} of {slots} weekly periods needed."})

    demand: dict[str, int] = defaultdict(int)
    for aid, a in c.assignments.items():
        demand[c.room_type(aid)] += a["periods"]
    for room_type, periods in sorted(demand.items()):
        cap = sum(1 for r in c.rooms.values() if r["type"] == room_type) * slots
        if periods > cap:
            out.append({"level": "error", "text": f"{type_name(room_type)}s are needed for {periods} periods but only {cap} are available.", "fix": "rooms"})
        else:
            out.append({"level": "ok", "text": f"{type_name(room_type)}s: {periods} of {cap} room-periods needed ({round(100 * periods / cap)}%)."})

    reported = set()
    for aid, a in c.assignments.items():
        g, room_type = c.groups[a["group"]], c.room_type(aid)
        key = (g.id, room_type)
        if key not in reported and not any(r["type"] == room_type and r["capacity"] >= g.strength for r in c.rooms.values()):
            reported.add(key)
            out.append({"level": "error", "text": f"No {type_name(room_type).lower()} is big enough for {c.group_label(g.id)} ({g.strength} students).", "fix": "rooms"})

    for tid, t in c.teachers.items():
        if off := sorted(c.unavailable.get(tid, ()), key=lambda x: (c.days.index(x[0]), x[1])):
            text = ", ".join(f"{d} {c.period_labels[p]}" for d, p in off)
            out.append({"level": "info", "text": f"{t['name']} is unavailable on {text}. Classes won't be placed there."})

    return sorted(out, key=lambda x: RANK[x["level"]])
