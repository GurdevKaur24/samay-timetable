"""What a head of department (HOD) may change: only their own department's courses, sections, teachers, subjects
and classes, plus their department's head and status. Everything else must stay exactly as it was."""

from collections import Counter

COORDINATOR_ONLY = {"name": "The college name", "place": "The college's place", "term": "The term", "kind": "The kind of college",
                    "scheme": "The college week (days, periods and rules)", "rooms": "Rooms"}
OWNED = [("courses", "Course"), ("sections", "Section"), ("teachers", "Teacher"), ("subjects", "Subject")]
DEPT_FIELDS_HOD_MAY_CHANGE = {"hod", "status"}


def class_key(a: dict) -> tuple:
    """A teaching assignment without its id: ids are renumbered when the list changes."""
    return a["subject"], a["group"], a["teacher"], a.get("periods")


def classes_outside(data: dict, dept: str) -> Counter:
    section_dept = {s["id"]: s["dept"] for s in data.get("sections", [])}
    return Counter(class_key(a) for a in data.get("assignments", []) if section_dept.get(a["group"].split("/")[0]) != dept)


def hod_problems(old: dict, new: dict, dept: str) -> list[str]:
    """Plain-English reasons a head of `dept` can't save `new` over `old` (empty if the change is allowed)."""
    dept_name = next((d["name"] for d in old.get("departments", []) if d["id"] == dept), dept)
    problems = [f"{label} can only be changed by the timetable coordinator." for key, label in COORDINATOR_ONLY.items()
                if old.get(key) != new.get(key)]

    old_depts = {d["id"]: d for d in old.get("departments", [])}
    new_depts = {d["id"]: d for d in new.get("departments", [])}
    if set(old_depts) != set(new_depts):
        problems.append("Only the timetable coordinator can add or remove departments.")
    else:
        for did, before in old_depts.items():
            after = new_depts[did]
            free = DEPT_FIELDS_HOD_MAY_CHANGE if did == dept else set()
            if {k: v for k, v in before.items() if k not in free} != {k: v for k, v in after.items() if k not in free}:
                problems.append(f"You can change only the head and status of {dept_name}. Ask the timetable coordinator to rename it."
                                if did == dept else f"Only the timetable coordinator can change the {before['name']} department.")

    for key, label in OWNED:
        before_all = {r["id"]: r for r in old.get(key, [])}
        after_all = {r["id"]: r for r in new.get(key, [])}
        for rid in sorted(set(before_all) | set(after_all)):
            before, after = before_all.get(rid), after_all.get(rid)
            if before == after:
                continue
            if (before is not None and before.get("dept") != dept) or (after is not None and after.get("dept") != dept):
                problems.append(f"{label} {rid}: you can only add, change or delete {dept_name}'s {key}.")

    if classes_outside(old, dept) != classes_outside(new, dept):
        problems.append(f"Classes for other departments' sections can only be changed by the timetable coordinator. "
                        f"You can change the classes of {dept_name}'s sections, taught by any teacher.")
    return problems
