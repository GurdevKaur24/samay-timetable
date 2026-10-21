"""Quality numbers for the scorecard. Lower gaps and more side-by-side sub-section labs = better."""

from collections import defaultdict

from .college import build


def metrics(data: dict, entries: list[dict]) -> dict:
    c = build(data)
    busy: dict[tuple, set[int]] = defaultdict(set)  # (student group, day) -> periods
    teacher_load: dict[str, int] = defaultdict(int)
    lab_slots = 0
    parallel_lab_slots = 0
    sub_busy: dict[tuple, set[str]] = defaultdict(set)  # (section, day, period) -> busy sub-sections

    for e in entries:
        a = c.assignments[e["assignment"]]
        g = c.groups[a["group"]]
        teacher_load[a["teacher"]] += 1
        # Students are the sub-sections (or the whole section if it has none).
        targets = [g.id] if g.is_sub else (c.subsections[g.section] or [g.section])
        for t in targets:
            busy[(t, e["day"])].add(e["period"])
        if g.is_sub:
            sub_busy[(g.section, e["day"], e["period"])].add(g.id)

    for (section, _, _), subs in sub_busy.items():
        lab_slots += 1
        if len(subs) == len(c.subsections[section]):
            parallel_lab_slots += 1

    gaps = []
    for periods in busy.values():
        span = [p for p in c.periods if min(periods) <= p <= max(periods)]
        gaps.append(len(span) - len(periods))
    avg_gaps = sum(gaps) / len(gaps) if gaps else 0.0
    last_period = sum(1 for e in entries if e["period"] == c.periods[-1])
    parallel_pct = 100.0 * parallel_lab_slots / lab_slots if lab_slots else 100.0

    score = 100 - 15 * avg_gaps - 0.3 * (100 - parallel_pct) - 0.5 * last_period
    loads = list(teacher_load.values()) or [0]
    return {
        "score": max(0, round(score)),
        "classes": len(entries),
        "avg_student_gaps": round(avg_gaps, 2),
        "parallel_labs_pct": round(parallel_pct),
        "last_period_classes": last_period,
        "teacher_load_min": min(loads),
        "teacher_load_max": max(loads),
        "rooms_used_pct": round(100 * len({(e["room"], e["day"], e["period"]) for e in entries}) / (len(c.rooms) * len(c.days) * len(c.periods))),
    }
