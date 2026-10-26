# Samay: College Timetable Optimizer

Web app that generates **clash-free** weekly timetables for any college (Hackathon 1, Punjab Jobs AI Bootcamp).
Full product plan and roadmap: `docs/requirements.md`.

## Stack
- **backend/**: Python 3.12, FastAPI, Google OR-Tools (CP-SAT), pytest.
  - `app/schema.py`: the one data format for a college (Pydantic), with plain-English field and cross-reference checks.
  - `solver/`: generator, clash checker, scorecard. Pure Python; reads college dicts in the schema format.
  - `data/colleges/*.json`: the demo college `demo-eng` (a full example). An empty one is made on request:
    `POST /api/auth/practice` (demo servers only) creates a private `practice-…` college with a passwordless coordinator
    and signs in; practice colleges older than a day are deleted. `POST /api/auth/practice/switch` (own practice college
    only) signs in as its head of department, a teacher or a student (accounts made on the fly). `tests/data/` holds a test-only second
    college (`city-arts`, with `test_users.json`) that `tests/conftest.py` adds, so privacy tests always have two colleges.
  - `app/db.py`: SQLite (`data/samay.db`, git-ignored, created and seeded on first start). Tables: colleges, users,
    sessions, college_data (one validated JSON document per college), timetables.
  - `app/auth.py`: `current_user` is the only source of a college id. Sign-in cookie `samay_session` (httpOnly,
    SameSite=Lax; set `SAMAY_COOKIE_SECURE=1` behind HTTPS). Passwords use scrypt; only token hashes are stored.
  - Demo accounts (a coordinator, a CSE head and a teacher for each demo college) are in `data/demo_users.json`. While `SAMAY_DEMO_LOGIN=1`
    (default) the sign-in page offers one-click demo sign-in (`/api/auth/demo-accounts`, `/api/auth/demo`), limited to
    those accounts. It must be off (`SAMAY_DEMO_LOGIN=0`) for any real deployment, since it lists the demo colleges.
  - `app/jobs.py`: generation runs in a background thread (one run per college at a time, time limit
    `SAMAY_SOLVE_SECONDS`, default 120). `solver.model.solve` works in two stages: any timetable with no clashes (no
    objective, presolve off: fast), then improving it from that hint until it hasn't got better for
    `SAMAY_SOLVE_PATIENCE` seconds (default 10). The job reports `progress` (stage, found, better_pct);
    `POST /api/jobs/{id}/stop` stops and keeps the best so far. To keep memory small, each class may use at most
    `SAMAY_MAX_ROOM_CHOICES` (6; 4 on Render) of the rooms that fit it (`room_choices`: smallest first, rotated so every room is used);
    `SAMAY_SOLVER_MEMORY_MB` (200 on Render, else none) caps the solver's memory, since the free plan's 512 MB limit
    otherwise stops the whole server. A timetable is saved only if the clash checker finds
    0 problems; versions are numbered per college and store the data they were built from.
  - `app/services/precheck.py`: plain-English pre-check (teacher load, section hours, room demand, room sizes).
  - `app/services/fingerprint.py`: a timetable is out of date only when scheduling data changed (not college or
    department names, heads or ready status). Revise/restore refuse out-of-date versions.
  - Locks: `{assignment, subject, group, day, start, room}`; the solver's `fixed=` keeps them in place; locks that no
    longer match the class (subject/group changed) are dropped with a message. Version numbers never repeat.
  - AI assistant (`routers/assistant.py`): Claude (`claude-opus-5-5`, tool runner), bound to the signed-in college.
    Coordinators: `SchedulingTools` on the latest version; `propose_change` only checks moves with the validator, the
    page previews it and saves through `/revise`. Heads of department and teachers: `WeekTools` on the published
    timetable a week at a time; their `propose_change` checks a change (`services/changes.check`) and the page applies it
    through `POST /api/changes`. Students (`POST /api/student/assistant`): look-up tools only. On only when
    `ANTHROPIC_API_KEY` is set (never in the code); `SAMAY_ASSISTANT=0` turns it off. Daily limits: site total
    `SAMAY_ASSISTANT_DAILY_LIMIT` (150), per head/teacher `SAMAY_ASSISTANT_PERSON_LIMIT` (20), per student phone
    `SAMAY_ASSISTANT_STUDENT_LIMIT` (10). Tests replace Claude with a stand-in.
  - Changes after publishing (`routers/changes.py`, `services/changes.py`, `services/change_store.py`, table
    `class_changes`): move or cancel a class **for one week** (`scope: once`, stored with its week; applied on top of the
    published version when a week is shown; never in the past, moves stay in the week, cancel is one-week only) or move it
    **from now on** (`always`: a new version, published at once, with the class locked there). A change is refused if it
    adds any validator problem. Coordinators: any class; HODs: classes whose sections are all in their department;
    teachers: their own classes. Coordinators list and undo every change; others their own. Publishing a new version
    carries one-week changes that still fit and removes the rest. "Today" uses `SAMAY_TIMEZONE` (Asia/Kolkata).
    `GET /api/published`, `/api/teacher` and `/api/student/timetable` take `?week=<any date>` and return `week`.
  - Invites and resets (`services/links.py`, `services/email.py`, table `password_tokens`): coordinators add people without
    a password (stored as `"!"`, which never matches) and get a one-time `/?invite=` link (7 days); forgot password and the
    coordinator's reset link give `/?reset=` (1 hour). Links are stored hashed, work once, and setting a password ends
    every session. Emailed through SMTP when `SAMAY_SMTP_HOST`/`SAMAY_EMAIL_FROM` are set; otherwise shown to copy.
    `/api/auth/forgot` answers the same for unknown emails. Tests pass `send_email=None` or a capturing stand-in.
  - Teachers may have an `email` (unique, ignored by the fingerprint). `POST /api/users/invite-teachers` invites every
    teacher (or the chosen ids) with an email and no account; others are skipped with a reason.
  - Sign-up (`SAMAY_SIGNUP`, default on) creates a college from `services/new_college.py` (Mon–Fri, 7 periods, lunch).
  - Roles: `coordinator` (everything; `coordinator_only` guards the timetables and users routers), `hod` (`users.dept_id`;
    may read college data and save it, but `services/departments.hod_problems` refuses any change outside their
    department's courses, sections, teachers, subjects, classes for its sections, and its head/status) and `teacher`
    (`users.teacher_id` links to a teacher record; `routers/teacher.py`: the published timetable without anyone's free
    times, and their own unavailable periods). Publishing (`colleges.published_version`) picks the version teachers see;
    only an up-to-date version can be published and the published one can't be deleted. `GET /api/published` serves it
    (without anyone's free times) to any signed-in user of the college.
  - Students (`routers/students.py`): no accounts. The coordinator turns on one student code per college
    (`colleges.student_code`, shown XXXX-XXXX, with a `/?code=` link and QR poster on the Accounts page). A phone that
    enters it gets a `samay_student` cookie (`student_sessions`, 180 days) that opens only that college's published
    timetable (`GET /api/student/timetable`); it opens nothing else. Wrong codes answer "not found" and are rate-limited
    per address; a new code or turning access off signs every phone out.
- **web/index.html**: the app's front end (one page). Served by the backend at http://localhost:8000 it runs in **live mode**
  (real sign-in; data loaded from and saved to the server with `PUT /api/college/data`; Generate uses the server's
  CP-SAT generator; assistant changes saved via `/revise`). Opened as a file, or from any other server, it falls back to
  **demo mode** (built-in demo colleges, in-browser generator, nothing saved). `fromServer`/`toServer` convert between
  the server schema and the page's in-memory format. Rebuild `tailwind.css` after adding new classes (command in
  `web/tailwind.config.cjs`).
  Signed out, it shows a home page (`homePage`, with the demo colleges under **Try the demo**); sign-in is `authView: 'signin'`.
  The coordinator's menu is Home plus the five steps from `steps(c)` (Your week, College data, Check for problems, Make
  the timetable, Publish & share), each page ending with `nextBar`. First-visit guides: `TOURS['role:page']` lists
  `[data-tour id, title, text]`; elements carry `data-tour="..."`; seen guides are remembered in localStorage for each
  account (`seenKey`); `?` replays. Without demo accounts (a real deployment) the home page shows sign-up and sign-in
  instead of the demo section.
  Every screen has an address (`#/timetable`, `#/data/teachers`, `#/signin`; `routeOf`/`applyRoute`), so Back,
  Forward and refresh work. Signed in with a demo account, a Demo bar switches role in one click (`switchDemo`); the
  public demo student code (DEMO-2026) comes with `/api/auth/demo-accounts`, never a college's own code.
- `services/demo.py`: with `SAMAY_DEMO_READY` (on by default when `RENDER` is set) the server generates and publishes
  demo-eng's timetable in the background at start and turns on student code DEMO-2026, since the free plan starts empty.
- **render.yaml**: deploys one free Render web service (API + page on one address, HTTPS cookies, 2 solver threads).
  The free plan has no disk, so the database is re-seeded with the demo colleges after restarts.

## Run
```
cd backend; .\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000   # app + API at http://localhost:8000
cd backend; .\.venv\Scripts\python -m app.seed --reset   # rebuild the local database from the seed files
cd backend; .\.venv\Scripts\python -m pytest
```

## Domain glossary
- **College structure**: Department → Course (programme, e.g. B.Tech CSE, MCA; has a duration in years) → Section
  (in one semester) → lab groups. Service departments (e.g. Applied Sciences) may have no courses.
- **Cross-department teaching**: teachers and subjects belong to a department ("offered by"), but any teacher can teach
  any department's sections, and the same subject can be taken by several departments. Never restrict a teacher to
  their own department; the clash rules alone keep them from being in two places at once.
- **Section**: a class group, e.g. CSE-3A (strength = number of students).
- **Sub-section**: lab split of a section, e.g. A → A1, A2. Lectures are taught to the whole section; labs to one sub-section;
  tutorials to either (many colleges take tutorials in lab groups), but not both for the same subject and section.
  A1 and A2 may do **different** lab subjects at the same time (A1 in the CN Lab, A2 in the DBMS Lab).
- **L-T-P**: weekly Lecture / Tutorial / Practical hours of a subject.
- **Assignment**: subject × (section or sub-section) × teacher, with required weekly periods. The teacher can be chosen
  by hand or picked by Samay (`auto: true`): the page's `pickTeachers` chooses someone who can teach the subject
  (`Teacher.subjects`, or already teaches it), balancing weekly load within each teacher's limit, preferring the
  subject's department and different teachers for a section's lab groups. Neither field changes the fingerprint.
- **Weekly periods** come from the college's `rules` (e.g. `lectures_per_week: 3`); a subject (`per_week`) or an
  assignment (`periods`) can override it. Every college sets its own; never assume one number for all colleges.
- **Period / slot**: one cell of the day × period grid. Lunch and breaks are not schedulable.
- **Elective group** (`electives`): students of several sections (possibly from several departments, e.g. an open
  elective) choose one of its subjects. The coordinator types how many students chose each subject; a subject with more
  than the college's `elective_class_size` (default 70) becomes batches (CV-1, CV-2), one teacher each (the same teacher
  may take several). Which students sit in which batch is up to the college. `solver.college.build` turns batches into
  assignments with ids `GROUP~SUBJECT~N`. Normal subjects never split (only labs, into lab groups).
- **Reserved time** (`reserved`): periods kept free for some sections, e.g. an open elective another department teaches
  at fixed times. No class of those sections (their lab groups or electives) is placed there; no teacher or room needed.

## Hard rules (never violated, checked by `solver/validator.py`)
1. A teacher, room, section or sub-section is never in two places in the same slot.
2. A whole-section class blocks the section **and all its sub-sections**; sub-sections can run different labs in parallel.
3. Room capacity ≥ group strength; room type matches (lab subjects need a lab of the right type).
4. Every assignment gets exactly its required weekly periods.
5. Labs are consecutive blocks (block_len) on one day, never crossing lunch or breaks.
6. Teacher unavailability and teacher max periods per day are respected.
7. While any class of an elective group runs, the group's sections have no other class (or other elective group).
8. Nothing is placed in a section's reserved times.

## Soft rules (objective)
Spread a subject across days (≤ 1 theory period of a subject per day where possible), few idle gaps, A1/A2 labs side by side,
an elective group's classes at the same time (in different rooms) where possible.

## Multi-college privacy (non-negotiable)
- Every user belongs to exactly one college. They see only that college's data and never learn which other colleges exist.
- The API takes the college from the signed-in user, never from a URL or request field. There is no "list all colleges"
  endpoint for college users; only the platform owner (super admin) can list colleges.
- Every stored record carries `college_id`, and every query filters on it. Tests must prove college A can't read college B.

## Conventions
- The **validator is the source of truth** for "0 clashes". Never mark a timetable valid without it.
- Solver and validator are pure Python (no FastAPI imports) and must have tests.
- Small Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`); keep `main` runnable.
- UI copy is plain English for non-technical college admins.
