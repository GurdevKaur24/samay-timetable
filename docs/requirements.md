# Requirements: Samay College Timetable Optimizer

## Problem
Colleges build timetables by hand every semester. Departments fit sections, labs and teachers into the week and
compete for shared rooms (seminar halls, computer labs). It takes weeks and still ends with clashes, uneven
teaching loads and empty rooms. Samay generates a clash-free, readable timetable for **any** college.

## Users and roles
| Role | What they do |
|---|---|
| Timetable coordinator | Sets up the college, its week and rooms; generates, edits and publishes; manages accounts and student access |
| HOD | Keeps their own department's courses, sections, teachers, subjects and classes up to date; marks it ready; moves or cancels their department's classes |
| Teacher | Sees their own week, marks periods they can't teach, moves or cancels their own classes |
| Student | No account: a college code (link or QR poster) opens the published timetable on a phone |

## Privacy between colleges
Many colleges use Samay, but each one is completely separate. A coordinator, HOD, teacher or student signs in to their
own college and sees only its teachers, rooms, scheme and timetables. Colleges can't see each other's data, or even which
other colleges use Samay. Only the platform owner can see the list of colleges, for support and billing.

## Core features
1. Institution setup: departments, time grid (days, periods, lunch and breaks)
2. Master data: rooms (type, capacity, shared or department), teachers (max load, unavailability),
   subjects (L-T-P, lab type, block length), sections with **sub-sections A1/A2**, teaching assignments
3. Excel/CSV import with error report by row; a demo college and an empty practice college
4. Pre-check with plain-English problems
5. **CP-SAT generator** respecting all hard rules
6. **Independent validator** with a "0 conflicts" badge
7. Views by section, teacher, room and department, with a readable colour-coded grid
8. Manual move/swap with live clash warnings; lock and re-generate
9. PDF and Excel export
10. Login, roles, data kept separate for each college
11. Samay picks a teacher for each class (from the subjects each teacher can teach), balancing loads

## Hard rules
- No teacher, room, section or sub-section double-booked
- A whole-section class blocks all sub-sections; A1 and A2 may hold different labs at the same time
- Capacity ≥ strength; room type matches
- Exact weekly periods for each assignment
- Labs in consecutive periods on one day, not crossing lunch or breaks
- Teacher unavailability and max periods per day
- While an elective group runs, its sections have no other class
- Nothing is placed in a section's reserved times

## Soft rules (quality score)
Subject spread across the week · few student and teacher gaps · A1/A2 labs side by side · balanced daily load ·
teacher preferences · fair use of shared rooms.

## Built beyond the core
- **AI assistant for every role** (Claude with tool use over our own functions): the coordinator's assistant explains
  clashes and proposes fixes shown as a **preview** (nothing saved until Apply, Undo after); heads of department and
  teachers ask it to move or cancel a class for one week or from now on; students ask look-up questions.
- Versions (view, restore, delete), publishing, one-week and permanent changes after publishing with Undo.
- Electives across sections and departments (big ones split into batches), reserved times, tutorials in lab groups.
- Invites and password resets by one-time links; student code with share link and QR poster.
- Guided first visit for every role; every screen has its own address (Back and refresh work).
- Deployed on Render (free plan) with one-click demo accounts.

## Still on the roadmap
- Infeasibility diagnosis that names the smallest set of conflicting rules.
- Daily substitutions (ranked substitute teachers), shared-room fairness report, compare versions side by side.
- iCal export, Punjabi/Hindi interface, a super-admin page for the platform owner.

## Scalability
- The generator pre-filters choices (room type, capacity, block length) and limits each class to a few rooms spread
  over all that fit, so the model stays small; it first finds any clash-free timetable, then improves it.
- A time limit, a memory cap and a fixed number of threads keep it safe on a small server.
- Production path: PostgreSQL, a job queue for generation, stateless API servers behind a load balancer,
  college_id on every row for privacy between colleges.
