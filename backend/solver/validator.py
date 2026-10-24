"""Independent checker for every hard rule.

It does not use the solver, so it can prove that any timetable (generated or hand-edited) has no clashes.
An entry is one occupied period: {"assignment": id, "day": "Mon", "period": 3, "room": "LH-101"}.
"""

from collections import defaultdict

from .college import College, build


def validate(data: dict, entries: list[dict]) -> list[dict]:
    c = build(data)
    violations: list[dict] = []
    seen: set[str] = set()

    def add(rule: str, message: str) -> None:
        if message not in seen:
            seen.add(message)
            violations.append({"rule": rule, "message": message})

    teacher_slots: dict[tuple, list[dict]] = defaultdict(list)
    room_slots: dict[tuple, list[dict]] = defaultdict(list)
    section_slots: dict[tuple, list[dict]] = defaultdict(list)
    per_assignment: dict[str, list[dict]] = defaultdict(list)
    teacher_day_load: dict[tuple, int] = defaultdict(int)

    for e in entries:
        a = c.assignments.get(e.get("assignment"))
        if a is None:
            add("unknown", f"Unknown class '{e.get('assignment')}' in the timetable.")
            continue
        day, period, room_id = e.get("day"), e.get("period"), e.get("room")
        if day not in c.days or period not in c.periods:
            add("unknown", f"{c.describe(a['id'])} is placed in a slot that doesn't exist ({day} {period}).")
            continue
        room = c.rooms.get(room_id)
        if room is None:
            add("unknown", f"{c.describe(a['id'])} uses an unknown room '{room_id}'.")
            continue

        slot = c.slot_label(day, period)
        group = c.groups[a["group"]]
        teacher = c.teachers[a["teacher"]]

        if room["type"] != c.room_type(a["id"]):
            add("room_type", f"{c.describe(a['id'])} needs a {c.room_type(a['id']).replace('_', ' ')} but is in {room_id} ({room['type'].replace('_', ' ')}) on {slot}.")
        if room["capacity"] < group.strength:
            add("capacity", f"{room_id} holds {room['capacity']} but {c.group_label(group.id)} has {group.strength} students ({slot}).")
        if (day, period) in c.unavailable.get(teacher["id"], set()):
            add("unavailable", f"{teacher['name']} is unavailable on {slot} but teaches {c.describe(a['id'])}.")

        teacher_slots[(teacher["id"], day, period)].append(e)
        room_slots[(room_id, day, period)].append(e)
        section_slots[(group.section, day, period)].append(e)
        per_assignment[a["id"]].append(e)
        teacher_day_load[(teacher["id"], day)] += 1

    for (tid, day, period), items in teacher_slots.items():
        if len(items) > 1:
            names = " and ".join(c.describe(i["assignment"]) for i in items)
            add("teacher_clash", f"{c.teachers[tid]['name']} is booked twice on {c.slot_label(day, period)}: {names}.")

    for (room_id, day, period), items in room_slots.items():
        if len(items) > 1:
            names = " and ".join(c.describe(i["assignment"]) for i in items)
            add("room_clash", f"{room_id} is double-booked on {c.slot_label(day, period)}: {names}.")

    # A whole-section class blocks every sub-section; sub-sections may run different classes in parallel.
    for (section, day, period), items in section_slots.items():
        whole = [i for i in items if not c.groups[c.assignments[i["assignment"]]["group"]].is_sub]
        by_sub: dict[str, list[dict]] = defaultdict(list)
        for i in items:
            g = c.groups[c.assignments[i["assignment"]]["group"]]
            if g.is_sub:
                by_sub[g.id].append(i)
        slot = c.slot_label(day, period)
        if len(whole) > 1:
            add("group_clash", f"{section} has two classes on {slot}: " + " and ".join(c.describe(i["assignment"]) for i in whole) + ".")
        if whole and by_sub:
            subs = ", ".join(c.describe(i["assignment"]) for v in by_sub.values() for i in v)
            add("group_clash", f"{section} has {c.describe(whole[0]['assignment'])} on {slot} while lab group classes also run ({subs}).")
        for sub_id, sub_items in by_sub.items():
            if len(sub_items) > 1:
                add("group_clash", f"{c.group_label(sub_id)} has two classes on {slot}: " + " and ".join(c.describe(i["assignment"]) for i in sub_items) + ".")

    # Electives: while any batch of a group runs, its sections have no other class (batches may run in parallel).
    for gid, e in c.electives.items():
        busy_times = {(i["day"], i["period"]) for bid in e["batches"] for i in per_assignment.get(bid, [])}
        for section in e["sections"]:
            for day, period in sorted(busy_times):
                others = section_slots.get((section, day, period), [])
                if others:
                    add("group_clash", f"{section} has {c.describe(others[0]['assignment'])} on {c.slot_label(day, period)}, "
                                       f"during {e['name']}.")
        for other_id, other in c.electives.items():
            if other_id <= gid or not set(e["sections"]) & set(other["sections"]):
                continue
            other_times = set().union(*({(i["day"], i["period"]) for i in per_assignment.get(b, [])} for b in other["batches"]))
            for day, period in sorted(busy_times & other_times):
                add("group_clash", f"{e['name']} and {other['name']} share sections but both run on {c.slot_label(day, period)}.")

    for aid, a in c.assignments.items():
        got = len(per_assignment.get(aid, []))
        if got != a["periods"]:
            add("hours", f"{c.describe(aid)} needs {a['periods']} periods a week but has {got}.")

        block = c.block(aid)
        if block > 1:
            by_day: dict[str, list[dict]] = defaultdict(list)
            for e in per_assignment.get(aid, []):
                by_day[e["day"]].append(e)
            for day, items in by_day.items():
                items.sort(key=lambda i: i["period"])
                run = [items[0]]
                runs = []
                for i in items[1:]:
                    prev = run[-1]["period"]
                    if i["period"] == prev + 1 and prev not in c.breaks_after and i["room"] == run[-1]["room"]:
                        run.append(i)
                    else:
                        runs.append(run)
                        run = [i]
                runs.append(run)
                for r in runs:
                    if len(r) % block != 0:
                        add("lab_block", f"{c.describe(aid)} on {day} must be {block} back-to-back periods in one room, without crossing a break.")

    for (tid, day), load in teacher_day_load.items():
        limit = c.teachers[tid].get("max_per_day")
        if limit is not None and load > limit:
            add("teacher_load", f"{c.teachers[tid]['name']} teaches {load} periods on {day}, above the limit of {limit}.")

    return violations
