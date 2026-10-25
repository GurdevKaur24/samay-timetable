import copy

import pytest
from pydantic import ValidationError

from app.schema import CollegeData
from solver.college import load_college, seed_college_ids


@pytest.mark.parametrize("college_id", seed_college_ids())
def test_seed_colleges_are_valid(college_id):
    CollegeData.model_validate(load_college(college_id))


def test_the_demo_colleges_exist():
    assert set(seed_college_ids()) == {"demo-eng", "gndec"}  # a full example, and an almost empty one to try your own data


def test_the_gndec_demo_starts_almost_empty():
    d = load_college("gndec")
    assert [x["id"] for x in d["departments"]] == ["CSE"] and [t["id"] for t in d["teachers"]] == ["G01"]
    assert not d["sections"] and not d["subjects"] and not d["assignments"] and not d["rooms"]


def broken(change):
    data = copy.deepcopy(load_college("demo-eng"))
    change(data)
    with pytest.raises(ValidationError) as e:
        CollegeData.model_validate(data)
    return str(e.value)


def test_section_must_be_in_a_known_course():
    assert "unknown course" in broken(lambda d: d["sections"][0].update(course="NOPE"))


def test_semester_must_fit_course_length():
    assert "has semesters 1–8" in broken(lambda d: d["sections"][0].update(sem=11))


def test_lab_must_go_to_a_lab_group():
    def change(d):
        lab = next(a for a in d["assignments"] if a["group"].endswith("/A1"))
        lab["group"] = lab["group"].split("/")[0]
    assert "must go to a lab group" in broken(change)


def test_teacher_can_teach_another_departments_section():
    # Cross-department teaching is allowed: a CSE teacher teaching an ECE section is valid data.
    data = load_college("demo-eng")
    cse_teacher = next(t["id"] for t in data["teachers"] if t["dept"] == "CSE")
    ece_section = next(s["id"] for s in data["sections"] if s["dept"] == "ECE")
    data["assignments"].append({"id": "X1", "subject": "HU301", "group": ece_section, "teacher": cse_teacher})
    CollegeData.model_validate(data)


def test_gap_between_periods_must_be_a_break():
    def change(d):
        d["scheme"]["breaks"] = []  # lunch removed but the gap in times is still there
    assert "Mark it as a break" in broken(change)


def test_unknown_department_is_reported():
    assert "unknown department" in broken(lambda d: d["teachers"][0].update(dept="XYZ"))
