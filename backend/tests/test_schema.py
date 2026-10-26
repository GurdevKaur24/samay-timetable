import copy

import pytest
from pydantic import ValidationError

from app.schema import CollegeData
from solver.college import load_college, seed_college_ids


@pytest.mark.parametrize("college_id", seed_college_ids())
def test_seed_colleges_are_valid(college_id):
    CollegeData.model_validate(load_college(college_id))


def test_the_demo_college_exists():
    assert set(seed_college_ids()) == {"demo-eng"}  # a full example; an empty one is made on request (practice)


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


def test_teachers_list_the_subjects_they_can_teach():
    d = load_college("demo-eng")
    d["teachers"][0]["subjects"] = ["NOPE"]
    with pytest.raises(ValidationError) as err:
        CollegeData.model_validate(d)
    assert "no such subject" in str(err.value)
    d["teachers"][0]["subjects"] = [d["subjects"][0]["id"]]
    d["assignments"][0]["auto"] = True
    CollegeData.model_validate(d)


def test_who_can_teach_what_and_auto_picks_dont_make_a_timetable_out_of_date():
    from app.services.fingerprint import schedule_fingerprint
    d = load_college("demo-eng")
    before = schedule_fingerprint(d)
    d["teachers"][0]["subjects"] = [d["subjects"][0]["id"]]
    d["assignments"][0]["auto"] = True
    assert schedule_fingerprint(d) == before
    d["assignments"][0]["teacher"] = d["teachers"][1]["id"]
    assert schedule_fingerprint(d) != before
