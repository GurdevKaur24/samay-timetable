# Requirements: Samay College Timetable Optimizer

## Problem
Colleges build timetables by hand every semester. Departments fit sections, labs and teachers into the week and
compete for shared rooms (seminar halls, computer labs). It takes weeks and still ends with clashes, uneven
teaching loads and empty rooms. Samay generates a clash-free, readable timetable for **any** college.

## Users and roles
| Role | What they do |
|---|---|
| Institution admin / Timetable coordinator | Set up college, time grid and rooms; generate, edit, publish |
| HOD | Manage own department's teachers, subjects, sections, assignments; approve |
| Teacher | View own timetable, set unavailability and preferences |
| Student / viewer | Read-only section timetable (public link, mobile) |

## Privacy between colleges
Many colleges use Samay, but each one is completely separate. A coordinator, HOD, teacher or student signs in to their
own college and sees only its teachers, rooms, scheme and timetables. Colleges can't see each other's data, or even which
other colleges use Samay. Only the platform owner can see the list of colleges, for support and billing.

## Core features
1. Institution setup: departments, time grid (days, periods, lunch and breaks)
2. Master data: rooms (type, capacity, shared or department), teachers (max load, unavailability),
   subjects (L-T-P, lab type, block length), sections with **sub-sections A1/A2**, teaching assignments
3. Excel/CSV import with error report by row; sample college
4. Pre-check with plain-English problems
5. **CP-SAT generator** respecting all hard rules
6. **Independent validator** with a "0 conflicts" badge
7. Views by section, teacher, room and department, with a readable colour-coded grid
8. Manual move/swap with live clash warnings; lock and re-generate
9. PDF and Excel export
10. Login, roles, data kept separate for each college

## Hard rules
- No teacher, room, section or sub-section double-booked
- A whole-section class blocks all sub-sections; A1 and A2 may hold different labs at the same time
- Capacity ≥ strength; room type matches
- Exact weekly periods for each assignment
- Labs in consecutive periods on one day, not crossing lunch or breaks
- Teacher unavailability and max periods per day

## Soft rules (quality score)
Subject spread across the week · few student and teacher gaps · A1/A2 labs side by side · balanced daily load ·
teacher preferences · fair use of shared rooms.

## Advanced (roadmap)
- **Scheduling Assistant bot**: explains clashes, suggests 1–3 fixes, and can update the schedule itself, but
  **always shows a preview first** (before/after diff, clash count and score change). Nothing is saved until the user clicks Apply;
  Discard and Undo are available. Built on the Claude API with tool use over our own backend functions.
- Infeasibility diagnosis, versions and comparison, shared-room fairness across departments, daily substitutions,
  electives and combined classes, public links, QR codes and iCal, Punjabi/Hindi UI.

## Hackathon sprint scope (2 hours)
- ✅ Must work: generate a clash-free timetable for the sample college (with A1/A2 labs), validator badge,
  section/teacher/room views, print to PDF.
- Prototype only ("Coming soon"): data tables, pre-check panel, assistant bot drawer with preview and Apply.
- Skipped for now: database, login, Excel import, drag-and-drop, deployment.

## Scalability
- Solver pre-filters choices (room type, capacity, block length), so the model stays small; time limit and multiple workers.
- Large colleges: solve by department with shared-room quotas, then a joint repair solve.
- Production path: PostgreSQL, background solve jobs (RQ/Redis), stateless API containers behind a load balancer,
  institution_id on every row for multi-tenancy.
