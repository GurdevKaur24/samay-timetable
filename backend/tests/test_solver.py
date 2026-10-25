import pytest

from solver.college import build, load_college, seed_college_ids, weekly_periods

from .conftest import TEST_DATA

COLLEGES = [(c, None) for c in seed_college_ids()] + [("city-arts", TEST_DATA)]
from solver.metrics import metrics
from solver.model import solve
from solver.validator import validate

RULES = {"lectures_per_week": 3, "lab_sessions_per_week": 1, "max_same_subject_per_day": 1}


def test_weekly_periods_follow_college_rule_unless_overridden():
    theory = {"kind": "theory"}
    lab = {"kind": "lab"}
    assert weekly_periods({}, theory, RULES) == 3
    assert weekly_periods({}, theory, {**RULES, "lectures_per_week": 4}) == 4
    assert weekly_periods({"periods": 2}, theory, RULES) == 2
    assert weekly_periods({}, {**theory, "per_week": 5}, RULES) == 5
    assert weekly_periods({}, lab, RULES, lab_block=2) == 2
    assert weekly_periods({}, lab, {**RULES, "lab_sessions_per_week": 2}, lab_block=3) == 6


@pytest.mark.parametrize("college_id,folder", COLLEGES)
def test_every_college_solves_with_no_clashes(college_id, folder):
    data = load_college(college_id, folder) if folder else load_college(college_id)
    result = solve(data, time_limit=30)
    assert result["status"] in ("optimal", "feasible")
    assert validate(data, result["entries"]) == []
    required = sum(a["periods"] for a in build(data).assignments.values())
    assert len(result["entries"]) == required
    assert metrics(data, result["entries"])["parallel_labs_pct"] == 100


def test_six_day_scheme_with_tea_break_is_respected():
    data = load_college("city-arts", TEST_DATA)
    c = build(data)
    assert len(c.days) == 6 and c.breaks_after == {2, 4}
    result = solve(data, time_limit=30)
    labs = [e for e in result["entries"] if c.block(e["assignment"]) > 1]
    # A lab block never starts right before a break.
    by_session = {}
    for e in labs:
        by_session.setdefault((e["assignment"], e["day"]), []).append(e["period"])
    assert all(not ({2, 3} <= set(p) or {4, 5} <= set(p)) for p in by_session.values())


def test_cross_department_teacher_is_never_double_booked():
    data = load_college("demo-eng")
    c = build(data)
    section_dept = {s["id"]: s["dept"] for s in data["sections"]}
    student_dept = lambda a: section_dept[c.groups[a["group"]].section]  # noqa: E731
    guests = {a["teacher"] for a in c.assignments.values() if c.teachers[a["teacher"]]["dept"] != student_dept(a)}
    # Applied Sciences teaches CSE and ECE; a CSE teacher teaches Data Structures to ECE.
    assert {"T09", "T03"} <= guests
    result = solve(data, time_limit=30)
    busy = {}
    for e in result["entries"]:
        teacher = c.assignments[e["assignment"]]["teacher"]
        if teacher in guests:
            slot = (teacher, e["day"], e["period"])
            assert slot not in busy, f"{teacher} is in two places on {e['day']} P{e['period']}"
            busy[slot] = e
    depts_taught = {t: {student_dept(c.assignments[e["assignment"]]) for e in result["entries"] if c.assignments[e["assignment"]]["teacher"] == t} for t in guests}
    assert all(depts - {c.teachers[t]["dept"]} for t, depts in depts_taught.items())  # each guest teaches outside their department
    assert depts_taught["T09"] == {"CSE", "ECE"} and depts_taught["T03"] == {"CSE", "ECE"}


def test_impossible_data_is_reported_not_crashed():
    data = load_college()
    data["assignments"][0]["periods"] = 40  # more than the whole week
    result = solve(data, time_limit=10)
    assert result["status"] == "infeasible"
    assert result["entries"] == []
