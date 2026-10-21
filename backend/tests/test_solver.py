from solver.college import build, load_college, weekly_periods
from solver.model import solve
from solver.validator import validate

RULES = {"lectures_per_week": 3, "lab_sessions_per_week": 1, "max_same_subject_per_day": 1}


def test_weekly_periods_follow_college_rule_unless_overridden():
    theory = {"kind": "theory"}
    lab = {"kind": "lab", "block": 2}
    assert weekly_periods({}, theory, RULES) == 3
    assert weekly_periods({}, theory, {**RULES, "lectures_per_week": 4}) == 4
    assert weekly_periods({"periods": 2}, theory, RULES) == 2
    assert weekly_periods({}, {**theory, "per_week": 5}, RULES) == 5
    assert weekly_periods({}, lab, RULES) == 2


def test_sample_college_solves_with_no_clashes():
    data = load_college()
    result = solve(data, time_limit=30)
    assert result["status"] in ("optimal", "feasible")
    assert validate(data, result["entries"]) == []
    required = sum(a["periods"] for a in build(data).assignments.values())
    assert len(result["entries"]) == required


def test_impossible_data_is_reported_not_crashed():
    data = load_college()
    data["assignments"][0]["periods"] = 40  # more than the whole week
    result = solve(data, time_limit=10)
    assert result["status"] == "infeasible"
    assert result["entries"] == []
