# Samay: College Timetable Optimizer

Web app that generates **clash-free** weekly timetables for any college (Hackathon 1, Punjab Jobs AI Bootcamp).
Full product plan and roadmap: `docs/requirements.md`.

## Stack
- **backend/**: Python 3.12, FastAPI, Google OR-Tools (CP-SAT), pytest.
  - `app/schema.py`: the one data format for a college (Pydantic), with plain-English field and cross-reference checks.
  - `solver/`: generator, clash checker, scorecard. Pure Python; reads college dicts in the schema format.
  - `data/colleges/*.json`: seed colleges (demo-eng, city-arts), exported from the prototype.
  - `app/db.py`: SQLite (`data/samay.db`, git-ignored, created and seeded on first start). Tables: colleges, users,
    sessions, college_data (one validated JSON document per college), timetables.
  - `app/auth.py`: `current_user` is the only source of a college id. Sign-in cookie `samay_session` (httpOnly,
    SameSite=Lax; set `SAMAY_COOKIE_SECURE=1` behind HTTPS). Passwords use scrypt; only token hashes are stored.
  - Demo accounts (a coordinator and a teacher per seed college, plus the CSE head at demo-eng) are in `data/demo_users.json`. While `SAMAY_DEMO_LOGIN=1`
    (default) the sign-in page offers one-click demo sign-in (`/api/auth/demo-accounts`, `/api/auth/demo`), limited to
    those accounts. It must be off (`SAMAY_DEMO_LOGIN=0`) for any real deployment, since it lists the demo colleges.
  - `app/jobs.py`: generation runs in a background thread (one run per college at a time, time limit
    `SAMAY_SOLVE_SECONDS`, default 30). A timetable is saved only if the clash checker finds 0 problems; versions are
    numbered per college and store the data they were built from.
  - `app/services/precheck.py`: plain-English pre-check (teacher load, section hours, room demand, room sizes).
  - `app/services/fingerprint.py`: a timetable is out of date only when scheduling data changed (not college or
    department names, heads or ready status). Revise/restore refuse out-of-date versions.
  - Locks: `{assignment, subject, group, day, start, room}`; the solver's `fixed=` keeps them in place; locks that no
    longer match the class (subject/group changed) are dropped with a message. Version numbers never repeat.
  - Sign-up (`SAMAY_SIGNUP`, default on) creates a college from `services/new_college.py` (Mon–Fri, 7 periods, lunch).
  - Roles: `coordinator` (everything; `coordinator_only` guards the timetables and users routers), `hod` (`users.dept_id`;
    may read college data and save it, but `services/departments.hod_problems` refuses any change outside their
    department's courses, sections, teachers, subjects, classes for its sections, and its head/status) and `teacher`
    (`users.teacher_id` links to a teacher record; `routers/teacher.py`: the published timetable without anyone's free
    times, and their own unavailable periods). Publishing (`colleges.published_version`) picks the version teachers see;
    only an up-to-date version can be published and the published one can't be deleted. `GET /api/published` serves it
    (without anyone's free times) to any signed-in user of the college.
    Students (planned, built last): a college code entered once, then any published section/teacher/room timetable.
- **prototype/index.html**: the app page. Served by the backend at http://localhost:8000 it runs in **live mode**
  (real sign-in; data loaded from and saved to the server with `PUT /api/college/data`; Generate uses the server's
  CP-SAT generator; assistant changes saved via `/revise`). Opened as a file, or from any other server, it falls back to
  **demo mode** (built-in demo colleges, in-browser generator, nothing saved). `fromServer`/`toServer` convert between
  the server schema and the page's in-memory format. Rebuild `tailwind.css` after adding new classes (command in
  `prototype/tailwind.config.cjs`).
- **frontend/**: React + Vite + TypeScript + Tailwind v4. Calls the API through the Vite proxy at `/api`.

## Run
```
cd backend; .\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
cd backend; .\.venv\Scripts\python -m app.seed --reset   # rebuild the local database from the seed files
cd backend; .\.venv\Scripts\python -m pytest
cd frontend; npm run dev            # http://localhost:5173
```

## Domain glossary
- **College structure**: Department → Course (programme, e.g. B.Tech CSE, MCA; has a duration in years) → Section
  (in one semester) → lab groups. Service departments (e.g. Applied Sciences) may have no courses.
- **Cross-department teaching**: teachers and subjects belong to a department ("offered by"), but any teacher can teach
  any department's sections, and the same subject can be taken by several departments. Never restrict a teacher to
  their own department; the clash rules alone keep them from being in two places at once.
- **Section**: a class group, e.g. CSE-3A (strength = number of students).
- **Sub-section**: lab split of a section, e.g. A → A1, A2. Theory is taught to the whole section; labs to one sub-section.
  A1 and A2 may do **different** lab subjects at the same time (A1 in the CN Lab, A2 in the DBMS Lab).
- **L-T-P**: weekly Lecture / Tutorial / Practical hours of a subject.
- **Assignment**: subject × (section or sub-section) × teacher, with required weekly periods.
- **Weekly periods** come from the college's `rules` (e.g. `lectures_per_week: 3`); a subject (`per_week`) or an
  assignment (`periods`) can override it. Every college sets its own; never assume one number for all colleges.
- **Period / slot**: one cell of the day × period grid. Lunch and breaks are not schedulable.

## Hard rules (never violated, checked by `solver/validator.py`)
1. A teacher, room, section or sub-section is never in two places in the same slot.
2. A whole-section class blocks the section **and all its sub-sections**; sub-sections can run different labs in parallel.
3. Room capacity ≥ group strength; room type matches (lab subjects need a lab of the right type).
4. Every assignment gets exactly its required weekly periods.
5. Labs are consecutive blocks (block_len) on one day, never crossing lunch or breaks.
6. Teacher unavailability and teacher max periods per day are respected.

## Soft rules (objective)
Spread a subject across days (≤ 1 theory period of a subject per day where possible), few idle gaps, A1/A2 labs side by side.

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
