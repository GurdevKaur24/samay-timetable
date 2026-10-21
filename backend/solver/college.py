"""Loading college data and building lookup tables shared by the solver, validator and metrics."""

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# Each college sets its own; these apply only when a college leaves a rule out.
DEFAULT_RULES = {
    "lectures_per_week": 3,  # weekly periods of a theory or tutorial subject
    "lab_sessions_per_week": 1,  # each session is `block` back-to-back periods
    "max_same_subject_per_day": 1,
}


def weekly_periods(assignment: dict, subject: dict, rules: dict) -> int:
    """Periods a week for one assignment: its own override, else the subject's, else the college rule."""
    if "periods" in assignment:
        return assignment["periods"]
    if "per_week" in subject:
        return subject["per_week"]
    if subject.get("kind") == "lab":
        return rules["lab_sessions_per_week"] * subject.get("block", 1)
    return rules["lectures_per_week"]


def load_college(name: str = "sample_college") -> dict:
    with open(DATA_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Group:
    """A set of students that attends classes together: a whole section or one of its sub-sections."""

    id: str
    section: str
    strength: int
    is_sub: bool


@dataclass
class College:
    data: dict
    days: list[str]
    periods: list[int]
    period_labels: dict[int, str]
    breaks_after: set[int]
    rooms: dict[str, dict]
    teachers: dict[str, dict]
    subjects: dict[str, dict]
    groups: dict[str, Group]
    subsections: dict[str, list[str]]  # section id -> sub-section ids
    assignments: dict[str, dict]
    rules: dict
    unavailable: dict[str, set[tuple[str, int]]] = field(default_factory=dict)

    def block(self, assignment_id: str) -> int:
        return self.subjects[self.assignments[assignment_id]["subject"]].get("block", 1)

    def room_type(self, assignment_id: str) -> str:
        return self.subjects[self.assignments[assignment_id]["subject"]].get("room_type", "lecture")

    def slot_label(self, day: str, period: int) -> str:
        return f"{day} {self.period_labels.get(period, f'P{period}')}"

    def describe(self, assignment_id: str) -> str:
        a = self.assignments[assignment_id]
        return f"{a['group']} {self.subjects[a['subject']]['short']}"

    def crosses_break(self, covered: list[int]) -> bool:
        """True if consecutive periods in `covered` are split by a break (e.g. lunch) or are not adjacent."""
        for prev, nxt in zip(covered, covered[1:]):
            if prev in self.breaks_after or nxt != prev + 1:
                return True
        return False


def build(data: dict) -> College:
    groups: dict[str, Group] = {}
    subsections: dict[str, list[str]] = {}
    for s in data["sections"]:
        groups[s["id"]] = Group(s["id"], s["id"], s["strength"], False)
        subsections[s["id"]] = []
        for sub in s.get("subsections", []):
            groups[sub["id"]] = Group(sub["id"], s["id"], sub["strength"], True)
            subsections[s["id"]].append(sub["id"])

    teachers = {t["id"]: t for t in data["teachers"]}
    subjects = {s["id"]: s for s in data["subjects"]}
    rules = {**DEFAULT_RULES, **data.get("rules", {})}
    assignments = {a["id"]: {**a, "periods": weekly_periods(a, subjects[a["subject"]], rules)} for a in data["assignments"]}
    return College(
        data=data,
        days=list(data["days"]),
        periods=[p["id"] for p in data["periods"]],
        period_labels={p["id"]: p["label"] for p in data["periods"]},
        breaks_after=set(data.get("breaks_after", [])),
        rooms={r["id"]: r for r in data["rooms"]},
        teachers=teachers,
        subjects=subjects,
        groups=groups,
        subsections=subsections,
        assignments=assignments,
        rules=rules,
        unavailable={tid: {(d, p) for d, p in t.get("unavailable", [])} for tid, t in teachers.items()},
    )
