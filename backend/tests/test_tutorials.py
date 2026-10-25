"""Tutorials can be taken by the whole section or in lab groups (A1, A2), like labs. Lectures stay whole-section."""

import copy

import pytest
from pydantic import ValidationError

from app.schema import CollegeData
from app.services.precheck import precheck
from solver.college import build, load_college
from solver.model import solve
from solver.validator import validate


def tutorials_in_lab_groups() -> dict:
    """Demo college where CSE-3A takes its Communication Skills tutorial in lab groups, each with its own teacher."""
    d = load_college("demo-eng")
    d["assignments"] = [a for a in d["assignments"] if a["id"] != "A05"]  # CSE-3A's whole-section HU301
    d["assignments"] += [{"id": "A91", "subject": "HU301", "group": "CSE-3A/A1", "teacher": "T10"},
                         {"id": "A92", "subject": "HU301", "group": "CSE-3A/A2", "teacher": "T11"}]
    return CollegeData.model_validate(d).model_dump(mode="json", exclude_none=True)


def test_a_tutorial_can_go_to_lab_groups():
    data = tutorials_in_lab_groups()
    result = solve(data, time_limit=30)
    assert result["status"] in ("optimal", "feasible")
    assert validate(data, result["entries"]) == []
    c = build(data)
    times = {aid: {(e["day"], e["period"]) for e in result["entries"] if e["assignment"] == aid} for aid in ("A91", "A92")}
    assert all(len(t) == c.assignments[aid]["periods"] for aid, t in times.items())
    whole = {(e["day"], e["period"]) for e in result["entries"] if c.assignments[e["assignment"]]["group"] == "CSE-3A"}
    assert not whole & (times["A91"] | times["A92"])  # never during a whole-section class


def test_a_lecture_still_needs_the_whole_section():
    d = load_college("demo-eng")
    d["assignments"].append({"id": "A93", "subject": "CS301", "group": "CSE-5A/A1", "teacher": "T01"})
    with pytest.raises(ValidationError) as err:
        CollegeData.model_validate(d)
    assert "is a lecture, so it's taught to the whole section" in str(err.value)


def test_a_tutorial_is_not_given_to_a_section_and_its_lab_group():
    d = load_college("demo-eng")
    d["assignments"].append({"id": "A94", "subject": "HU301", "group": "CSE-3A/A1", "teacher": "T11"})  # A05 already gives it to CSE-3A
    with pytest.raises(ValidationError) as err:
        CollegeData.model_validate(d)
    assert "also to its lab group CSE-3A/A1" in str(err.value)


def test_precheck_notices_a_lab_group_left_without_its_tutorial():
    d = copy.deepcopy(tutorials_in_lab_groups())
    d["assignments"] = [a for a in d["assignments"] if a["id"] != "A92"]
    assert any(i["level"] == "warn" and "given to CSE-3A A1 but not to CSE-3A A2" in i["text"] for i in precheck(d))
