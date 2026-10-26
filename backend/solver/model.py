"""CP-SAT timetable generator.

Decision variable x[assignment, day, start, room] = 1 when a session of that assignment starts there.
Choices are pre-filtered (room type and capacity, lab block fits before a break, teacher available), so the model stays small.
"""

import threading
import time
from collections import defaultdict

from ortools.sat.python import cp_model

from .college import build

PARALLEL_LAB_WEIGHT = 10  # A1 busy while A2 is idle (and vice versa)
ELECTIVE_SPREAD_WEIGHT = 4  # per period an elective group keeps its sections busy: prefer its options at the same time
LATE_PERIOD_COST = {6: 1, 7: 3}  # prefer finishing the day early


class _Improvements(cp_model.CpSolverSolutionCallback):
    """Remembers when the timetable last got noticeably better (lower cost)."""

    def __init__(self, on_better=None):
        super().__init__()
        self.best: float | None = None
        self.improved_at: float | None = None
        self.on_better = on_better

    def on_solution_callback(self):
        value = self.ObjectiveValue()
        if self.best is None or value < self.best - max(1.0, 0.005 * abs(self.best)):
            self.improved_at = time.perf_counter()
        if self.best is None or value < self.best:
            self.best = value
            if self.on_better:
                self.on_better(value)


def solve(data: dict, time_limit: float = 20.0, workers: int = 8, fixed: list[dict] | None = None,
          patience: float | None = None, stop: threading.Event | None = None, on_progress=None) -> dict:
    """`fixed` lists locked sessions that must stay exactly where they are:
    [{"assignment": id, "day": "Mon", "start": 3, "room": "LH-101"}] (start = first period of the session).

    Two stages: first any timetable with no clashes, found fast (no quality goal, no presolve); then that one is
    improved (fewer gaps, labs side by side, ...). `patience`: stop improving once the best timetable hasn't got
    noticeably better for this many seconds (the search for a better one rarely ends on its own). `stop`: set it to
    stop at once and keep the best timetable so far. `on_progress(stage=..., found=..., cost=...)` reports progress."""
    report = on_progress or (lambda **_: None)
    stop = stop or threading.Event()
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

    deadline = started + time_limit

    def run(model, callback=None, settle=False, **params):
        """One solver run until it ends, the time limit, `stop`, or (with `settle`) no improvement for `patience`."""
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(1.0, deadline - time.perf_counter())
        solver.parameters.num_search_workers = workers
        for name, value in params.items():
            setattr(solver.parameters, name, value)
        done, settled = threading.Event(), threading.Event()

        def watch():
            while not done.wait(0.25):
                calm = settle and patience and callback.improved_at is not None and time.perf_counter() - callback.improved_at >= patience
                if stop.is_set() or calm:
                    settled.set()
                    solver.StopSearch()
                    return

        threading.Thread(target=watch, daemon=True).start()
        status = solver.Solve(model, callback) if callback else solver.Solve(model)
        done.set()
        return solver, status, settled.is_set()

    report(stage="searching", found=False)
    first = None  # stage 1: any timetable with no clashes, values by variable index
    if cost_terms and not stop.is_set():
        quick = cp_model.CpModel()
        quick.Proto().CopyFrom(m.Proto())
        quick.Proto().ClearField("objective")
        quick_solver, quick_status, _ = run(quick, cp_model_presolve=False)
        if quick_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            first = list(quick_solver.ResponseProto().solution)
            m.Proto().solution_hint.vars.extend(range(len(first)))
            m.Proto().solution_hint.values.extend(first)
            report(stage="improving", found=True)
        elif quick_status == cp_model.INFEASIBLE:
            return _no_timetable(started, cp_model.INFEASIBLE, fixed)

    solver, status, stopped = None, cp_model.UNKNOWN, stop.is_set()
    if not stop.is_set() and time.perf_counter() < deadline - 1:  # stage 2: make it better
        progress = _Improvements(on_better=lambda cost: report(stage="improving", found=True, cost=cost))
        solver, status, stopped = run(m, progress, settle=True, max_presolve_iterations=1)
    elapsed = round(time.perf_counter() - started, 2)

    improved = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    if improved:
        chosen = solver.Value
    elif first is not None:  # stopped before stage 2 found anything: keep stage 1's timetable
        chosen, status = (lambda v: first[v.Index()]), cp_model.FEASIBLE
    else:
        if stop.is_set():
            return {"status": "stopped", "message": "Stopped before a timetable was found.", "entries": [], "seconds": elapsed}
        return _no_timetable(started, status, fixed)

    entries = [
        {"assignment": aid, "day": day, "period": p, "room": room}
        for aid, options in starts.items()
        for v, day, start, room, covered in options
        if chosen(v)
        for p in covered
    ]
    return {
        "status": "optimal" if status == cp_model.OPTIMAL else "feasible",
        "message": "Timetable generated.",
        "entries": entries,
        "seconds": elapsed,
        "objective": solver.ObjectiveValue() if improved and cost_terms else None,
        "stopped_early": stopped,
    }


def _no_timetable(started: float, status, fixed: list[dict] | None) -> dict:
    reason = "No timetable can satisfy all the rules with this data." if status == cp_model.INFEASIBLE else "No timetable found within the time limit."
    if fixed:
        reason += f" {len(fixed)} class(es) are locked; try unlocking some of them."
    return {"status": "infeasible", "message": reason, "entries": [], "seconds": round(time.perf_counter() - started, 2)}

def _fail(started: float, message: str) -> dict:
    return {"status": "infeasible", "message": message, "entries": [], "seconds": round(time.perf_counter() - started, 2)}
