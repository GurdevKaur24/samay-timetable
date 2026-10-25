"""CP-SAT timetable generator.

Decision variable x[assignment, day, start, room] = 1 when a session of that assignment starts there.
Choices are pre-filtered (room type and capacity, lab block fits before a break, teacher available), so the model stays small.
"""

import time
from collections import defaultdict

from ortools.sat.python import cp_model

from .college import build

PARALLEL_LAB_WEIGHT = 10  # A1 busy while A2 is idle (and vice versa)
ELECTIVE_SPREAD_WEIGHT = 4  # per period an elective group keeps its sections busy: prefer its options at the same time
LATE_PERIOD_COST = {6: 1, 7: 3}  # prefer finishing the day early


def solve(data: dict, time_limit: float = 20.0, workers: int = 8, fixed: list[dict] | None = None) -> dict:
    """`fixed` lists locked sessions that must stay exactly where they are:
    [{"assignment": id, "day": "Mon", "start": 3, "room": "LH-101"}] (start = first period of the session)."""
    c = build(data)
    started = time.perf_counter()
    m = cp_model.CpModel()

    starts: dict[str, list] = defaultdict(list)  # assignment -> [(var, day, start, room, covered)]
    occ: dict[tuple, list] = defaultdict(list)  # (assignment, day, period) -> vars covering it
    room_occ: dict[tuple, list] = defaultdict(list)  # (room, day, period) -> vars
    cost_terms = []

    for aid, a in c.assignments.items():
        block = c.block(aid)
        if a["periods"] % block != 0:
            return _fail(started, f"{c.describe(aid)} has {a['periods']} periods, which isn't a multiple of its block length {block}.")
        group = c.groups[a["group"]]
        rooms = [r for r in c.rooms.values() if r["type"] == c.room_type(aid) and r["capacity"] >= group.strength]
        if not rooms:
            return _fail(started, f"No {c.room_type(aid).replace('_', ' ')} is big enough for {c.group_label(group.id)} ({group.strength} students).")
        unavailable = c.unavailable.get(a["teacher"], set())
        sections = c.sections_of(aid)  # reserved times of these sections are never used

        for day in c.days:
            for i, start in enumerate(c.periods):
                covered = c.periods[i : i + block]
                if len(covered) < block or c.crosses_break(covered):
                    continue
                if any((day, p) in unavailable for p in covered):
                    continue
                if any((s, day, p) in c.reserved for s in sections for p in covered):
                    continue
                for r in rooms:
                    v = m.NewBoolVar(f"x_{aid}_{day}_{start}_{r['id']}")
                    starts[aid].append((v, day, start, r["id"], covered))
                    for p in covered:
                        occ[(aid, day, p)].append(v)
                        room_occ[(r["id"], day, p)].append(v)
                    late = sum(LATE_PERIOD_COST.get(p, 0) for p in covered)
                    if late:
                        cost_terms.append(late * v)

        sessions = a["periods"] // block
        m.Add(sum(v for v, *_ in starts[aid]) == sessions)
        for day in c.days:  # spread a subject across the week (college rule, usually once a day)
            m.Add(sum(v for v, d, *_ in starts[aid] if d == day) <= c.rules["max_same_subject_per_day"])

    for f in fixed or []:
        aid = f["assignment"]
        if aid not in c.assignments:
            return _fail(started, "A locked class no longer exists in your data. Unlock it and generate again.")
        match = [v for v, day, start, room, _ in starts[aid] if day == f["day"] and start == f["start"] and room == f["room"]]
        where = f"{f['day']} {c.period_labels.get(f['start'], f['start'])} in {f['room']}"
        if not match:
            return _fail(started, f"{c.describe(aid)} is locked on {where}, but it can't be there any more "
                                  "(the room, the teacher's availability or the timings changed). Unlock it and generate again.")
        m.Add(match[0] == 1)

    # Electives: whenever any batch of a group runs, the group's sections have nothing else (any of their students may
    # be in it). Batches may run in parallel (different students); running them together is preferred (soft).
    elective_busy: dict[tuple, list] = defaultdict(list)  # (section, day, period) -> "group is running" indicators
    for gid, e in c.electives.items():
        for day in c.days:
            for p in c.periods:
                vs = [v for bid in e["batches"] for v in occ.get((bid, day, p), [])]
                if not vs:
                    continue
                running = m.NewBoolVar(f"e_{gid}_{day}_{p}")
                for v in vs:
                    m.Add(running >= v)
                cost_terms.append(ELECTIVE_SPREAD_WEIGHT * running)
                for section in e["sections"]:
                    elective_busy[(section, day, p)].append(running)

    by_teacher: dict[str, list[str]] = defaultdict(list)
    by_group: dict[str, list[str]] = defaultdict(list)
    for aid, a in c.assignments.items():
        by_teacher[a["teacher"]].append(aid)
        by_group[a["group"]].append(aid)

    def busy(aids: list[str], day: str, p: int) -> list:
        return [v for aid in aids for v in occ.get((aid, day, p), [])]

    for day in c.days:
        for p in c.periods:
            for tid, aids in by_teacher.items():
                vs = busy(aids, day, p)
                if len(vs) > 1:
                    m.AddAtMostOne(vs)
            for vs in (room_occ.get((rid, day, p), []) for rid in c.rooms):
                if len(vs) > 1:
                    m.AddAtMostOne(vs)
            for section, subs in c.subsections.items():
                whole = busy(by_group[section], day, p) + elective_busy.get((section, day, p), [])
                for sub in subs or [None]:
                    vs = whole + (busy(by_group[sub], day, p) if sub else [])
                    if len(vs) > 1:
                        m.AddAtMostOne(vs)
                # Soft: keep sub-sections in step, so one isn't idle while the other is in a lab.
                if len(subs) >= 2:
                    first = sum(whole + busy(by_group[subs[0]], day, p))
                    for other in subs[1:]:
                        diff = m.NewBoolVar(f"d_{section}_{other}_{day}_{p}")
                        second = sum(whole + busy(by_group[other], day, p))
                        m.Add(diff >= first - second)
                        m.Add(diff >= second - first)
                        cost_terms.append(PARALLEL_LAB_WEIGHT * diff)

    for tid, aids in by_teacher.items():
        limit = c.teachers[tid].get("max_per_day")
        if limit is None:
            continue
        for day in c.days:
            load = [v for p in c.periods for v in busy(aids, day, p)]
            if len(load) > limit:
                m.Add(sum(load) <= limit)

    if cost_terms:
        m.Minimize(sum(cost_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    status = solver.Solve(m)
    elapsed = round(time.perf_counter() - started, 2)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        reason = "No timetable can satisfy all the rules with this data." if status == cp_model.INFEASIBLE else "No timetable found within the time limit."
        if fixed:
            reason += f" {len(fixed)} class(es) are locked; try unlocking some of them."
        return {"status": "infeasible", "message": reason, "entries": [], "seconds": elapsed}

    entries = [
        {"assignment": aid, "day": day, "period": p, "room": room}
        for aid, options in starts.items()
        for v, day, start, room, covered in options
        if solver.Value(v)
        for p in covered
    ]
    return {
        "status": "optimal" if status == cp_model.OPTIMAL else "feasible",
        "message": "Timetable generated.",
        "entries": entries,
        "seconds": elapsed,
        "objective": solver.ObjectiveValue() if cost_terms else 0,
    }


def _fail(started: float, message: str) -> dict:
    return {"status": "infeasible", "message": message, "entries": [], "seconds": round(time.perf_counter() - started, 2)}
