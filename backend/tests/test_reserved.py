"""Reserved times: periods kept free for some sections (e.g. an open elective another department teaches at fixed
times). No class of those sections, their lab groups or their electives is ever placed there."""

import copy

import pytest
from pydantic import ValidationError

from app.schema import CollegeData
from app.services.precheck import precheck
from solver.college import build
from solver.model import solve
from solver.validator import validate

from .test_electives import final_year_college
from .test_timetables import generate

OE_II = {"id": "OE-II", "name": "Open Elective-II (other departments)", "sections": ["CSE-7A", "CSE-7B"],
         "slots": [["Mon", 1], ["Wed", 1], ["Fri", 1]]}
SPORTS = {"id": "SPORTS", "name": "Sports period", "sections": ["CSE-3A", "CSE-5A"], "slots": [["Thu", 6], ["Thu", 7]]}


def with_reserved() -> dict:
    d = final_year_college()
    d["reserved"] = [OE_II, SPORTS]
    return CollegeData.model_validate(d).model_dump(mode="json", exclude_none=True)


@pytest.fixture(scope="module")
def college():
    return with_reserved()


@pytest.fixture(scope="module")
def solved(college):
    result = solve(college, time_limit=30)
    assert result["status"] in ("optimal", "feasible"), result["message"]
    return result["entries"]


def test_reserved_times_stay_free(college, solved):
    assert validate(college, solved) == []
    c = build(college)
    for e in solved:
        for s in c.sections_of(e["assignment"]):
            assert (s, e["day"], e["period"]) not in c.reserved, e  # covers lab groups (CSE-3A/A1) and electives


def test_a_class_in_a_reserved_time_is_a_clash(college, solved):
    moved = [dict(e) for e in solved]
    spm = next(e for e in moved if e["assignment"] == "A90")  # CSE-7A's Software Project Management
    spm.update(day="Mon", period=1)
    problems = [p["message"] for p in validate(college, moved)]
    assert any("kept free for Open Elective-II" in m and "CSE-7A" in m for m in problems)


@pytest.mark.parametrize("change,expect", [
    (lambda r: r.update(sections=["NOPE"]), "unknown section"),
    (lambda r: r.update(slots=[["Sun", 1]]), "aren't in the college week"),
    (lambda r: r.update(slots=[["Mon", 1], ["Mon", 1]]), "lists a time twice"),
])
def test_reserved_time_mistakes_are_explained(college, change, expect):
    d = copy.deepcopy(college)
    change(d["reserved"][0])
    with pytest.raises(ValidationError) as err:
        CollegeData.model_validate(d)
    assert expect in str(err.value)


def test_precheck_counts_reserved_times(college):
    items = precheck(college)
    assert any(i["level"] == "ok" and i["text"].startswith("CSE-7A: 6 of 32 weekly periods needed (3 kept free)") for i in items)
    d = copy.deepcopy(college)
    d["reserved"][0]["slots"] = [[day, p] for day in d["scheme"]["days"] for p in range(1, 7)]  # leaves 5 periods
    assert any(i["level"] == "error" and "CSE-7A needs 6 periods" in i["text"] for i in precheck(d))


def test_reserved_times_through_the_api(eng, hod):
    body = eng.get("/api/college/data").json()
    assert eng.put("/api/college/data", json={"version": body["version"], "data": with_reserved() | {"id": "demo-eng"}}).status_code == 200
    job = generate(eng)
    assert job["status"] == "done", job["message"]
    t = eng.get("/api/timetables/latest").json()
    assert eng.post(f"/api/timetables/{t['version']}/check").json()["clashes"] == 0
    body = hod.get("/api/college/data").json()  # heads of department can't change reserved times
    body["data"]["reserved"][0]["slots"].append(["Tue", 2])
    r = hod.put("/api/college/data", json={"version": body["version"], "data": body["data"]})
    assert r.status_code == 403 and "Reserved times" in " ".join(r.json()["detail"]["problems"])
