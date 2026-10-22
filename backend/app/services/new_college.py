"""A brand-new college starts with a common week it can change in the scheme editor, and no other data."""

import re
import secrets


def college_id_for(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "college"
    return f"{slug}-{secrets.token_hex(3)}"


def empty_college(college_id: str, name: str, place: str = "", term: str = "") -> dict:
    times = [("09:00", "09:50"), ("09:50", "10:40"), ("10:40", "11:30"), ("11:30", "12:20"),
             ("13:00", "13:50"), ("13:50", "14:40"), ("14:40", "15:30")]
    return {
        "id": college_id, "name": name, "place": place, "term": term, "kind": "",
        "scheme": {
            "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
            "periods": [{"label": f"P{i}", "start": s, "end": e} for i, (s, e) in enumerate(times, start=1)],
            "breaks": [{"after": 4, "label": "Lunch"}],
            "theory_room_type": "lecture", "lab_block": 2, "lab_prefix": "section",
            "rules": {"lectures_per_week": 3, "lab_sessions_per_week": 1, "max_same_subject_per_day": 1, "teacher_max_per_day": 5},
        },
        "departments": [], "courses": [], "sections": [], "teachers": [], "rooms": [], "subjects": [], "assignments": [],
    }
