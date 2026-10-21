# Samay: College Timetable Optimizer

Web app that generates **clash-free** weekly timetables for any college (Hackathon 1, Punjab Jobs AI Bootcamp).
Full product plan and roadmap: `docs/requirements.md`.

## Stack
- **backend/**: Python 3.12, FastAPI, Google OR-Tools (CP-SAT), pytest. Data is in `backend/data/*.json` for now (no DB yet).
- **frontend/**: React + Vite + TypeScript + Tailwind v4. Calls the API through the Vite proxy at `/api`.

## Run
```
cd backend; .\.venv\Scripts\activate; uvicorn app:app --reload --port 8000
cd backend; .\.venv\Scripts\python -m pytest
cd frontend; npm run dev            # http://localhost:5173
```

## Domain glossary
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
