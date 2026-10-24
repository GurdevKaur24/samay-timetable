"""The one data format for a college: its scheme and all its records.

Field checks live on the models; checks that need several records (does this section's course exist? is a lab given to a
lab group?) live in `CollegeData.check_references`. Every message is plain English for college admins.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from solver.college import batch_count, weekly_periods

ALL_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TIME = r"^([01]\d|2[0-3]):[0-5]\d$"
Kind = Literal["theory", "tutorial", "lab"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class Period(Model):
    label: str = Field(min_length=1)
    start: str = Field(pattern=TIME)
    end: str = Field(pattern=TIME)


class Break(Model):
    after: int = Field(ge=1, description="The break comes after this period number (1 = after P1).")
    label: str = Field(min_length=1)


class Rules(Model):
    lectures_per_week: int = Field(3, ge=1, le=28)
    lab_sessions_per_week: int = Field(1, ge=1, le=7)
    max_same_subject_per_day: int = Field(1, ge=1, le=4)
    teacher_max_per_day: int = Field(5, ge=1, le=16)
    elective_class_size: int = Field(70, ge=1, le=1000, description="Most students in one elective class; bigger electives are split into batches.")


class Scheme(Model):
    days: list[str] = Field(min_length=1)
    periods: list[Period] = Field(min_length=1)
    breaks: list[Break] = []
    theory_room_type: str = "lecture"
    lab_block: int = Field(2, ge=1)
    lab_prefix: str = Field("section", description='"section" names lab groups after the section (A1, A2); otherwise a fixed prefix like "G".')
    rules: Rules = Rules()

    @model_validator(mode="after")
    def check_week(self):
        problems = []
        if bad := [d for d in self.days if d not in ALL_DAYS]:
            problems.append(f"Unknown day(s): {', '.join(bad)}. Use {', '.join(ALL_DAYS)}.")
        if len(set(self.days)) != len(self.days):
            problems.append("A working day is listed twice.")
        breaks = {b.after for b in self.breaks}
        for i, p in enumerate(self.periods, start=1):
            if minutes(p.end) <= minutes(p.start):
                problems.append(f"{p.label} must end after it starts.")
            if i > 1:
                prev = self.periods[i - 2]
                gap = minutes(p.start) - minutes(prev.end)
                if gap < 0:
                    problems.append(f"{p.label} starts before {prev.label} ends.")
                elif gap > 0 and (i - 1) not in breaks:
                    problems.append(f"There's a gap between {prev.label} and {p.label} ({prev.end}–{p.start}). Mark it as a break, or close the gap.")
                elif gap == 0 and (i - 1) in breaks:
                    problems.append(f"The break after {prev.label} has no time. Leave a gap before {p.label}.")
        if any(b.after >= len(self.periods) for b in self.breaks):
            problems.append("A break can't come after the last period.")
        if self.lab_block > len(self.periods):
            problems.append(f"Labs of {self.lab_block} periods don't fit in a {len(self.periods)}-period day.")
        week = len(self.days) * self.rules.max_same_subject_per_day
        if self.rules.lectures_per_week > week:
            problems.append(f"{self.rules.lectures_per_week} lectures a week don't fit: the week allows at most {week} per subject.")
        if problems:
            raise ValueError(" ".join(problems))
        return self


class Department(Model):
    id: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1)
    hod: str | None = None
    status: Literal["ready", "review"] = "ready"


class Course(Model):
    id: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1)
    dept: str
    years: int = Field(ge=1, le=6)


class LabGroup(Model):
    label: str = Field(min_length=1)
    strength: int = Field(ge=1)


class Section(Model):
    id: str = Field(min_length=1, pattern=r"^[^/]+$")
    dept: str
    course: str | None = None
    sem: int | None = Field(None, ge=1)
    strength: int = Field(ge=1, le=1000)
    lab_groups: list[LabGroup] = []


class Teacher(Model):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    dept: str
    max_per_day: int | None = Field(None, ge=1)
    unavailable: list[tuple[str, int]] = []


class Room(Model):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    capacity: int = Field(ge=1, le=1000)
    owner: str = "Shared"


class Subject(Model):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9-]+$")
    short: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Kind
    dept: str | None = None
    room_type: str | None = None
    per_week: int | None = Field(None, ge=1)


class Assignment(Model):
    id: str = Field(min_length=1)
    subject: str
    group: str = Field(description='A section id ("CSE-3A") for lectures, or a lab group ("CSE-3A/A1") for labs.')
    teacher: str
    periods: int | None = Field(None, ge=1)


class ElectiveOption(Model):
    """One subject students can choose in an elective group. Samay splits it into batches of at most the class size."""
    subject: str
    students: int = Field(ge=1, le=5000, description="How many students chose it.")
    teachers: list[str] = Field(min_length=1, description="One teacher per batch, in order (the same teacher may take several).")
    batches: int | None = Field(None, ge=1, le=20, description="Number of batches; worked out from the class size if left out.")


class Elective(Model):
    """Subjects students choose between (e.g. Departmental Elective-II). While any of its classes runs, every section in
    `sections` is kept free (any of their students may be in it). Running its classes at the same time is preferred."""
    id: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(min_length=1)
    sections: list[str] = Field(min_length=1, description="Sections whose students choose from it (can be from several departments).")
    options: list[ElectiveOption] = Field(min_length=1)
    periods: int | None = Field(None, ge=1, description="Periods a week; from the college rules if left out.")


class CollegeData(Model):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    place: str = ""
    term: str = ""
    kind: str = ""
    scheme: Scheme
    departments: list[Department] = []
    courses: list[Course] = []
    sections: list[Section] = []
    teachers: list[Teacher] = []
    rooms: list[Room] = []
    subjects: list[Subject] = []
    assignments: list[Assignment] = []
    electives: list[Elective] = []

    @model_validator(mode="after")
    def check_references(self):
        problems: list[str] = []
        for label, items in [("department", self.departments), ("course", self.courses), ("section", self.sections),
                             ("teacher", self.teachers), ("room", self.rooms), ("subject", self.subjects), ("teaching assignment", self.assignments)]:
            ids = [x.id for x in items]
            if dupes := sorted({i for i in ids if ids.count(i) > 1}):
                problems.append(f"Two {label}s have the same code: {', '.join(dupes)}.")

        depts = {d.id for d in self.departments}
        courses = {c.id: c for c in self.courses}
        subjects = {s.id: s for s in self.subjects}
        teachers = {t.id for t in self.teachers}
        sections = {s.id for s in self.sections}
        lab_groups = {f"{s.id}/{g.label}" for s in self.sections for g in s.lab_groups}
        n_periods = len(self.scheme.periods)

        for c in self.courses:
            if c.dept not in depts:
                problems.append(f"Course {c.name} belongs to an unknown department {c.dept}.")
        for s in self.sections:
            if s.dept not in depts:
                problems.append(f"Section {s.id} belongs to an unknown department {s.dept}.")
            if s.course is not None:
                course = courses.get(s.course)
                if course is None:
                    problems.append(f"Section {s.id} is in an unknown course {s.course}.")
                else:
                    if course.dept != s.dept:
                        problems.append(f"Section {s.id} is in {course.name}, which belongs to {course.dept}, not {s.dept}.")
                    if s.sem is not None and s.sem > course.years * 2:
                        problems.append(f"Section {s.id} is in semester {s.sem}, but {course.name} has semesters 1–{course.years * 2}.")
            labels = [g.label for g in s.lab_groups]
            if len(set(labels)) != len(labels):
                problems.append(f"Section {s.id} has two lab groups with the same name.")
        for t in self.teachers:
            if t.dept not in depts:
                problems.append(f"{t.name} belongs to an unknown department {t.dept}.")
            for day, period in t.unavailable:
                if day not in self.scheme.days or not 1 <= period <= n_periods:
                    problems.append(f"{t.name} is marked unavailable on {day} P{period}, which isn't in the college week.")
        for r in self.rooms:
            if r.owner != "Shared" and r.owner not in depts:
                problems.append(f"Room {r.id} belongs to an unknown department {r.owner}.")
        for s in self.subjects:
            if s.dept is not None and s.dept not in depts:
                problems.append(f"Subject {s.id} is offered by an unknown department {s.dept}.")
            if s.kind == "lab" and not s.room_type:
                problems.append(f"Lab subject {s.id} needs a lab room type.")

        seen = set()
        for a in self.assignments:
            s = subjects.get(a.subject)
            if s is None:
                problems.append(f"Teaching assignment {a.id} uses an unknown subject {a.subject}.")
            if a.teacher not in teachers:
                problems.append(f"Teaching assignment {a.id} uses an unknown teacher {a.teacher}.")
            if a.group not in sections and a.group not in lab_groups:
                problems.append(f"Teaching assignment {a.id} is for an unknown section or lab group {a.group}.")
            elif s is not None and s.kind == "lab" and a.group not in lab_groups:
                problems.append(f"{s.short} is a lab, so it must go to a lab group, not the whole section {a.group}.")
            elif s is not None and s.kind != "lab" and a.group in lab_groups:
                problems.append(f"{s.short} is taught to the whole section, not to lab group {a.group}.")
            if s is not None and s.kind == "lab" and a.periods is not None and a.periods % self.scheme.lab_block:
                problems.append(f"{s.short} for {a.group} has {a.periods} periods, which isn't a multiple of the lab length ({self.scheme.lab_block}).")
            if (a.subject, a.group) in seen:
                problems.append(f"{a.subject} is assigned to {a.group} twice.")
            seen.add((a.subject, a.group))

        size = self.scheme.rules.elective_class_size
        if dupes := sorted({e.id for e in self.electives if [x.id for x in self.electives].count(e.id) > 1}):
            problems.append(f"Two elective groups have the same code: {', '.join(dupes)}.")
        for e in self.electives:
            if bad := [x for x in e.sections if x not in sections]:
                problems.append(f"{e.name} is for unknown section(s): {', '.join(bad)}.")
            if len(set(e.sections)) != len(e.sections):
                problems.append(f"{e.name} lists a section twice.")
            kinds = set()
            for o in e.options:
                s = subjects.get(o.subject)
                if s is None:
                    problems.append(f"{e.name} has an unknown subject {o.subject}.")
                    continue
                kinds.add("lab" if s.kind == "lab" else "class")
                if bad := [t for t in o.teachers if t not in teachers]:
                    problems.append(f"{e.name}: {s.short} has unknown teacher(s) {', '.join(bad)}.")
                n = batch_count(o.students, o.batches, size)
                if len(o.teachers) < n:
                    problems.append(f"{e.name}: {s.short} has {o.students} students, so {n} batches of up to {size}, "
                                    f"but only {len(o.teachers)} teacher(s). Add a teacher for each batch (the same teacher can take more than one).")
            if len(kinds) > 1:
                problems.append(f"{e.name} mixes labs and lectures. Put lab electives in their own elective group.")
            weekly = {weekly_periods({}, subjects[o.subject].model_dump(), self.scheme.rules.model_dump(), self.scheme.lab_block)
                      for o in e.options if o.subject in subjects}
            if e.periods is None and len(weekly) > 1:
                problems.append(f"The subjects in {e.name} have different periods a week ({', '.join(map(str, sorted(weekly)))}). "
                                "They run together, so set the periods a week on the elective group.")
            if len({o.subject for o in e.options}) != len(e.options):
                problems.append(f"{e.name} lists a subject twice.")
            if e.periods is not None and "lab" in kinds and e.periods % self.scheme.lab_block:
                problems.append(f"{e.name} has {e.periods} periods, which isn't a multiple of the lab length ({self.scheme.lab_block}).")

        if problems:
            raise ValueError(" ".join(problems))
        return self
