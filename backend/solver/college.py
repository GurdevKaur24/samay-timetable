"""Loading college data and building lookup tables shared by the solver, validator and metrics.

Input is a college in the format described by `app/schema.py` (as a plain dict). The solver package stays
independent of the web app: it only reads dicts.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

COLLEGES_DIR = Path(__file__).resolve().parent.parent / "data" / "colleges"

# Each college sets its own; these apply only when a college leaves a rule out.
DEFAULT_RULES = {
    "lectures_per_week": 3,  # weekly periods of a lecture or tutorial subject
    "lab_sessions_per_week": 1,  # each session is `lab_block` back-to-back periods
    "max_same_subject_per_day": 1,
    "teacher_max_per_day": 5,
    "elective_class_size": 70,  # most students in one elective class; bigger electives are split into batches
}


def weekly_periods(assignment: dict, subject: dict, rules: dict, lab_block: int = 2) -> int:
    """Periods a week for one assignment: its own override, else the subject's, else the college rule."""
    if assignment.get("periods") is not None:
        return assignment["periods"]
    if subject.get("per_week") is not None:
        return subject["per_week"]
    if subject.get("kind") == "lab":
        return rules["lab_sessions_per_week"] * lab_block
    return rules["lectures_per_week"]


def batch_count(students: int, batches: int | None, class_size: int) -> int:
    """How many batches an elective subject runs: as set, or enough classes of at most `class_size`."""
    return batches or max(1, -(-students // class_size))


def batch_sizes(students: int, n: int) -> list[int]:
    """Students split as evenly as possible over n batches (the college decides who goes where)."""
    return [students // n + (1 if i < students % n else 0) for i in range(n)]


def seed_college_ids() -> list[str]:
    return sorted(p.stem for p in COLLEGES_DIR.glob("*.json"))


def load_college(college_id: str = "demo-eng") -> dict:
    with open(COLLEGES_DIR / f"{college_id}.json", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Group:
    """A set of students that attends classes together: a whole section or one of its lab groups."""

    id: str  # "CSE-3A" or "CSE-3A/A1"
    section: str
    label: str  # "CSE-3A" or "A1"
    strength: int
    is_sub: bool
    elective: str | None = None  # set for an elective batch: the elective group's id


@dataclass
class College:
    data: dict
    days: list[str]
    periods: list[int]
    period_labels: dict[int, str]
    breaks_after: set[int]
    theory_room_type: str
    lab_block: int
    rooms: dict[str, dict]
    teachers: dict[str, dict]
    subjects: dict[str, dict]
    groups: dict[str, Group]
    subsections: dict[str, list[str]]  # section id -> lab group ids
    assignments: dict[str, dict]
    rules: dict
    unavailable: dict[str, set[tuple[str, int]]] = field(default_factory=dict)
    # Elective groups: id -> {"name", "sections" (kept free while it runs), "batches" (assignment ids, all at the same time)}
    electives: dict[str, dict] = field(default_factory=dict)

    def block(self, assignment_id: str) -> int:
        subject = self.subjects[self.assignments[assignment_id]["subject"]]
        return self.lab_block if subject["kind"] == "lab" else 1

    def room_type(self, assignment_id: str) -> str:
        subject = self.subjects[self.assignments[assignment_id]["subject"]]
        if subject["kind"] == "lab":
            return subject.get("room_type") or self.theory_room_type
        return self.theory_room_type

    def slot_label(self, day: str, period: int) -> str:
        return f"{day} {self.period_labels.get(period, f'P{period}')}"

    def group_label(self, group_id: str) -> str:
        g = self.groups[group_id]
        if g.elective:
            return f"{g.label} ({self.electives[g.elective]['name']})"
        return f"{g.section} {g.label}" if g.is_sub else g.id

    def describe(self, assignment_id: str) -> str:
        a = self.assignments[assignment_id]
        if self.groups[a["group"]].elective:
            return self.group_label(a["group"])
        return f"{self.group_label(a['group'])} {self.subjects[a['subject']]['short']}"

    def crosses_break(self, covered: list[int]) -> bool:
        """True if consecutive periods in `covered` are split by a break (e.g. lunch) or are not adjacent."""
        for prev, nxt in zip(covered, covered[1:]):
            if prev in self.breaks_after or nxt != prev + 1:
                return True
        return False


def build(data: dict) -> College:
    scheme = data["scheme"]
    rules = {**DEFAULT_RULES, **scheme.get("rules", {})}
    lab_block = scheme.get("lab_block", 2)

    groups: dict[str, Group] = {}
    subsections: dict[str, list[str]] = {}
    for s in data["sections"]:
        groups[s["id"]] = Group(s["id"], s["id"], s["id"], s["strength"], False)
        subsections[s["id"]] = []
        for g in s.get("lab_groups", []):
            gid = f"{s['id']}/{g['label']}"
            groups[gid] = Group(gid, s["id"], g["label"], g["strength"], True)
            subsections[s["id"]].append(gid)

    teachers = {t["id"]: {**t, "max_per_day": t.get("max_per_day") or rules["teacher_max_per_day"]} for t in data["teachers"]}
    subjects = {s["id"]: s for s in data["subjects"]}
    assignments = {a["id"]: {**a, "periods": weekly_periods(a, subjects[a["subject"]], rules, lab_block)} for a in data["assignments"]}
    # Each elective subject becomes one or more batches (classes of at most the class size): each batch is its own "group"
    # (the students who chose it) and its own assignment. While any batch runs, the group's sections have no other class.
    electives: dict[str, dict] = {}
    for e in data.get("electives", []):
        first = subjects[e["options"][0]["subject"]]
        periods = e.get("periods") or weekly_periods({}, first, rules, lab_block)
        batches = []
        for o in e["options"]:
            subject = subjects[o["subject"]]
            n = batch_count(o["students"], o.get("batches"), rules["elective_class_size"])
            for k, (size, teacher) in enumerate(zip(batch_sizes(o["students"], n), o["teachers"]), start=1):
                bid = f"{e['id']}~{o['subject']}~{k}"
                label = f"{subject['short']}-{k}" if n > 1 else subject["short"]
                groups[bid] = Group(bid, bid, label, size, False, elective=e["id"])
                assignments[bid] = {"id": bid, "subject": o["subject"], "group": bid, "teacher": teacher, "periods": periods, "elective": e["id"]}
                batches.append(bid)
        electives[e["id"]] = {"name": e["name"], "sections": list(e["sections"]), "batches": batches}

    periods = list(range(1, len(scheme["periods"]) + 1))
    return College(
        data=data,
        days=list(scheme["days"]),
        periods=periods,
        period_labels={i: p["label"] for i, p in zip(periods, scheme["periods"])},
        breaks_after={b["after"] for b in scheme.get("breaks", [])},
        theory_room_type=scheme.get("theory_room_type", "lecture"),
        lab_block=lab_block,
        rooms={r["id"]: r for r in data["rooms"]},
        teachers=teachers,
        subjects=subjects,
        groups=groups,
        subsections=subsections,
        assignments=assignments,
        rules=rules,
        unavailable={tid: {(d, p) for d, p in t.get("unavailable", [])} for tid, t in teachers.items()},
        electives=electives,
    )
