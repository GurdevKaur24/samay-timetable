"""Electives: students of several sections choose between subjects. Big electives split into batches of at most the
class size. While any elective class runs, its sections have no other class; running the options together is preferred."""

import copy

import pytest
from pydantic import ValidationError

from app.schema import CollegeData
from app.services.fingerprint import schedule_fingerprint
from app.services.precheck import precheck
from solver.college import build, load_college
from solver.model import solve
from solver.validator import validate

from .test_timetables import generate


def final_year_college() -> dict:
    """The demo engineering college plus a final year: 2 sections choosing a departmental elective, and an open
    elective taken by 5th-semester CSE and ECE students, big enough to need 2 batches."""
    d = load_college("demo-eng")
    d["sections"] += [{"id": f"CSE-7{x}", "dept": "CSE", "course": "BTECH-CSE", "sem": 7, "strength": 60} for x in "AB"]
    d["teachers"] += [{"id": f"T9{i}", "name": f"Prof. Final {i}", "dept": "CSE"} for i in range(6)]
    d["subjects"] += [
        {"id": "CS701", "short": "AI", "name": "Artificial Intelligence", "kind": "theory", "dept": "CSE"},
        {"id": "CS702", "short": "IoT", "name": "Internet of Things", "kind": "theory", "dept": "CSE"},
        {"id": "CS703", "short": "CC", "name": "Cloud Computing", "kind": "theory", "dept": "CSE"},
        {"id": "CS710", "short": "SPM", "name": "Software Project Management", "kind": "theory", "dept": "CSE"},
        {"id": "OE01", "short": "ECO", "name": "Engineering Economics", "kind": "theory", "dept": "AS"},
        {"id": "OE02", "short": "DM", "name": "Disaster Management", "kind": "theory", "dept": "AS"},
    ]
    d["assignments"] += [{"id": f"A9{i}", "subject": "CS710", "group": f"CSE-7{x}", "teacher": "T95"} for i, x in enumerate("AB")]
    d["electives"] = [
        {"id": "DE-I", "name": "Departmental Elective-I", "sections": ["CSE-7A", "CSE-7B"], "options": [
            {"subject": "CS701", "students": 60, "teachers": ["T90"]},
            {"subject": "CS702", "students": 40, "teachers": ["T91"]},
            {"subject": "CS703", "students": 20, "teachers": ["T92"]}]},
        {"id": "OE-I", "name": "Open Elective-I", "sections": ["CSE-5A", "ECE-5A"], "options": [
            {"subject": "OE01", "students": 100, "teachers": ["T93", "T94"]},
            {"subject": "OE02", "students": 8, "teachers": ["T93"]}]},
    ]
    return CollegeData.model_validate(d).model_dump(mode="json", exclude_none=True)


@pytest.fixture(scope="module")
def college():
    return final_year_college()


@pytest.fixture(scope="module")
def solved(college):
    result = solve(college, time_limit=30)
    assert result["status"] in ("optimal", "feasible"), result["message"]
    return result["entries"]


def times_of(entries, aids):
    return {(e["day"], e["period"]) for e in entries if e["assignment"] in aids}


# ---- batches ------------------------------------------------------------------------------------------------
def test_electives_become_batches(college):
    c = build(college)
    oe = c.electives["OE-I"]["batches"]
    labels = [c.groups[b].label for b in oe]
    assert labels == ["ECO-1", "ECO-2", "DM"]  # 100 students in classes of up to 70 -> 2 batches; DM fits one
    assert [c.groups[b].strength for b in oe] == [50, 50, 8]
    assert [c.assignments[b]["teacher"] for b in oe] == ["T93", "T94", "T93"]  # one teacher may take two batches
    assert len(c.electives["DE-I"]["batches"]) == 3  # each departmental elective fits one room
    assert c.describe(oe[0]) == "ECO-1 (Open Elective-I)"


def test_class_size_is_set_by_each_college(college):
    d = copy.deepcopy(college)
    d["scheme"]["rules"]["elective_class_size"] = 30
    d["electives"][0]["options"][0]["teachers"] = ["T90", "T91"]
    d["electives"][0]["options"][1]["teachers"] = ["T91", "T91"]  # the same teacher takes both IoT batches
    d["electives"][1]["options"][0]["teachers"] = ["T93", "T94", "T93", "T94"]
    c = build(CollegeData.model_validate(d).model_dump(mode="json", exclude_none=True))
    assert [c.groups[b].label for b in c.electives["DE-I"]["batches"]] == ["AI-1", "AI-2", "IoT-1", "IoT-2", "CC"]


@pytest.mark.parametrize("change,expect", [
    (lambda d: d["electives"][1]["options"][0].update(teachers=["T93"]), "Add a teacher for each batch"),
    (lambda d: d["electives"][0].update(sections=["CSE-7A", "NOPE"]), "unknown section"),
    (lambda d: d["electives"][0]["options"].append({"subject": "CS301L", "students": 10, "teachers": ["T90"]}), "mixes labs and lectures"),
    (lambda d: d["electives"][0]["options"].append({"subject": "CS701", "students": 10, "teachers": ["T90"]}), "lists a subject twice"),
    (lambda d: d["subjects"][-6].update(per_week=4), "different periods a week"),
    (lambda d: d["electives"][0]["options"][0].update(teachers=["NOPE"]), "unknown teacher"),
])
def test_elective_mistakes_are_explained(college, change, expect):
    d = copy.deepcopy(college)
    change(d)
    with pytest.raises(ValidationError) as err:
        CollegeData.model_validate(d)
    assert expect in str(err.value)


# ---- generating -------------------------------------------------------------------------------------------
def test_electives_are_scheduled_with_no_clashes(college, solved):
    assert validate(college, solved) == []
    c = build(college)
    for e in c.electives.values():
        for bid in e["batches"]:
            assert len([x for x in solved if x["assignment"] == bid]) == c.assignments[bid]["periods"]


def test_sections_have_nothing_else_while_their_elective_runs(college, solved):
    c = build(college)
    for e in c.electives.values():
        running = times_of(solved, e["batches"])
        for section in e["sections"]:
            own = {aid for aid, a in c.assignments.items() if not a.get("elective") and c.groups[a["group"]].section == section}
            assert not times_of(solved, own) & running


def test_options_are_preferably_at_the_same_time(college, solved):
    c = build(college)
    e = c.electives["DE-I"]
    periods = c.assignments[e["batches"][0]]["periods"]
    assert len(times_of(solved, e["batches"])) == periods  # all three options run together


# ---- the clash checker --------------------------------------------------------------------------------------
def test_a_class_during_an_elective_is_a_clash(college, solved):
    c = build(college)
    elective_time = sorted(times_of(solved, c.electives["DE-I"]["batches"]))[0]
    spm = next(x for x in solved if x["assignment"] == "A90")
    moved = [dict(x) for x in solved]
    for x in moved:
        if x is not None and x["assignment"] == "A90" and (x["day"], x["period"]) == (spm["day"], spm["period"]):
            x.update(day=elective_time[0], period=elective_time[1], room="Seminar Hall")
    problems = [p["message"] for p in validate(college, moved)]
    assert any("CSE-7A" in m and "Departmental Elective-I" in m for m in problems)


def test_options_may_run_at_different_times(college, solved):
    """Running together is only preferred: moving one option to a free slot is still valid."""
    c = build(college)
    cc = c.electives["DE-I"]["batches"][2]
    busy = {(x["day"], x["period"]) for x in solved
            if x["assignment"] in {a for a, v in c.assignments.items() if v.get("elective") == "DE-I" or c.groups[v["group"]].section in ("CSE-7A", "CSE-7B") or v["teacher"] == "T92"}}
    rooms_busy = {(x["room"], x["day"], x["period"]) for x in solved}
    free = next((d, p) for d in c.days for p in c.periods if (d, p) not in busy and ("LH-101", d, p) not in rooms_busy)
    moved = [dict(x) for x in solved]
    first = next(x for x in moved if x["assignment"] == cc)
    first.update(day=free[0], period=free[1], room="LH-101")
    assert validate(college, moved) == []


# ---- pre-check ------------------------------------------------------------------------------------------------
def test_precheck_counts_elective_periods_and_rooms(college):
    items = precheck(college)
    assert any(i["level"] == "ok" and i["text"].startswith("CSE-7A: 6 of") for i in items)  # SPM 3 + elective 3
    d = copy.deepcopy(college)
    d["rooms"] = [r for r in d["rooms"] if r["id"] in ("LH-101", "CL-1", "CL-2", "EL-1", "EL-2")]
    assert any(i["level"] == "warn" and "not enough" in i["text"] and "Departmental Elective-I" in i["text"] for i in precheck(d))


# ---- through the API ----------------------------------------------------------------------------------------
def test_coordinator_saves_electives_and_generates(eng):
    body = eng.get("/api/college/data").json()
    r = eng.put("/api/college/data", json={"version": body["version"], "data": final_year_college() | {"id": "demo-eng"}})
    assert r.status_code == 200, r.json()
    job = generate(eng)
    assert job["status"] == "done", job["message"]
    t = eng.get("/api/timetables/latest").json()
    assert eng.post(f"/api/timetables/{t['version']}/check").json()["clashes"] == 0
    assert any("~" in x["assignment"] for x in t["entries"])  # elective batches are in the timetable


def test_heads_of_department_cannot_change_electives(eng, hod):
    body = eng.get("/api/college/data").json()
    eng.put("/api/college/data", json={"version": body["version"], "data": final_year_college() | {"id": "demo-eng"}})
    body = hod.get("/api/college/data").json()
    body["data"]["electives"][0]["options"][0]["students"] = 61
    r = hod.put("/api/college/data", json={"version": body["version"], "data": body["data"]})
    assert r.status_code == 403 and "Electives" in " ".join(r.json()["detail"]["problems"])


def test_changing_electives_makes_the_timetable_out_of_date(college):
    d = copy.deepcopy(college)
    d["electives"][0]["options"][1]["students"] = 41
    assert schedule_fingerprint(d) != schedule_fingerprint(college)
