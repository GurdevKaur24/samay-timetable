"""Each hard rule has a passing case and a failing case on a tiny hand-made college."""

import copy

from solver.validator import validate

COLLEGE = {
    "id": "tiny", "name": "Tiny College",
    "scheme": {
        "days": ["Mon", "Tue"],
        "periods": [{"label": f"P{i}", "start": s, "end": e} for i, (s, e) in
                    enumerate([("09:00", "10:00"), ("10:00", "11:00"), ("11:30", "12:30"), ("12:30", "13:30")], start=1)],
        "breaks": [{"after": 2, "label": "Tea"}],
        "theory_room_type": "lecture", "lab_block": 2, "lab_prefix": "section",
        "rules": {"lectures_per_week": 2, "lab_sessions_per_week": 1, "max_same_subject_per_day": 1, "teacher_max_per_day": 4},
    },
    "departments": [{"id": "CSE", "name": "Computer Science"}],
    "courses": [{"id": "BT", "name": "B.Tech", "dept": "CSE", "years": 4}],
    "sections": [{"id": "S", "dept": "CSE", "course": "BT", "sem": 1, "strength": 60,
                  "lab_groups": [{"label": "A1", "strength": 30}, {"label": "A2", "strength": 30}]}],
    "teachers": [{"id": "T1", "name": "Dr. One", "dept": "CSE"}, {"id": "T2", "name": "Dr. Two", "dept": "CSE", "unavailable": [["Mon", 1]]},
                 {"id": "T3", "name": "Dr. Three", "dept": "CSE"}],
    "rooms": [{"id": "LH", "type": "lecture", "capacity": 60}, {"id": "LAB1", "type": "computer_lab", "capacity": 30},
              {"id": "LAB2", "type": "computer_lab", "capacity": 30}],
    "subjects": [{"id": "TH", "short": "Theory", "name": "Theory", "kind": "theory"},
                 {"id": "LA", "short": "Lab A", "name": "Lab A", "kind": "lab", "room_type": "computer_lab"},
                 {"id": "LB", "short": "Lab B", "name": "Lab B", "kind": "lab", "room_type": "computer_lab"}],
    "assignments": [{"id": "a_th", "subject": "TH", "group": "S", "teacher": "T1"},
                    {"id": "a_l1", "subject": "LA", "group": "S/A1", "teacher": "T2"},
                    {"id": "a_l2", "subject": "LB", "group": "S/A2", "teacher": "T3"}],
}

# A1 and A2 do different labs at the same time (P3–P4), after the theory class.
VALID = [
    {"assignment": "a_th", "day": "Mon", "period": 1, "room": "LH"},
    {"assignment": "a_th", "day": "Tue", "period": 1, "room": "LH"},
    {"assignment": "a_l1", "day": "Mon", "period": 3, "room": "LAB1"},
    {"assignment": "a_l1", "day": "Mon", "period": 4, "room": "LAB1"},
    {"assignment": "a_l2", "day": "Mon", "period": 3, "room": "LAB2"},
    {"assignment": "a_l2", "day": "Mon", "period": 4, "room": "LAB2"},
]


def rules_broken(entries, college=COLLEGE):
    return {v["rule"] for v in validate(college, entries)}


def moved(index, **changes):
    entries = copy.deepcopy(VALID)
    entries[index].update(changes)
    return entries


def test_valid_timetable_has_no_violations():
    assert validate(COLLEGE, VALID) == []


def test_lab_groups_can_run_different_labs_in_parallel():
    assert "group_clash" not in rules_broken(VALID)


def test_teacher_double_booked():
    college = copy.deepcopy(COLLEGE)
    college["assignments"][2]["teacher"] = "T2"  # T2 now runs both labs at once
    assert "teacher_clash" in rules_broken(VALID, college)


def test_room_double_booked():
    entries = moved(4, room="LAB1")
    entries[5]["room"] = "LAB1"
    assert "room_clash" in rules_broken(entries)


def test_whole_section_class_blocks_lab_groups():
    assert "group_clash" in rules_broken(moved(1, day="Mon", period=3))


def test_room_too_small_and_wrong_type():
    broken = rules_broken(moved(0, room="LAB1"))
    assert {"capacity", "room_type"} <= broken


def test_wrong_number_of_periods():
    assert "hours" in rules_broken(VALID[1:])


def test_lab_cannot_cross_a_break():
    entries = moved(2, period=2)  # P2 + P4 with the tea break in between
    assert "lab_block" in rules_broken(entries)


def test_teacher_unavailability():
    entries = moved(2, period=1)
    entries[3]["period"] = 2
    assert "unavailable" in rules_broken(entries)


def test_messages_use_readable_lab_group_names():
    college = copy.deepcopy(COLLEGE)
    college["assignments"][2]["teacher"] = "T2"
    text = " ".join(v["message"] for v in validate(college, VALID))
    assert "S A1" in text and "S/A1" not in text
