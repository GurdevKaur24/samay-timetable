# Samay: College Timetable Optimizer

Generates **clash-free** weekly timetables for any college: sections, lab sub-sections (A1/A2), teachers and shared rooms.
Every result is re-checked by an independent validator, so you can see "0 conflicts" for yourself.

Built for Hackathon 1, Punjab Jobs AI Bootcamp (J-PAL South Asia).

## What it does
- Generates a timetable with Google OR-Tools (CP-SAT) while respecting every hard rule (no teacher, room or section clashes,
  room capacity and type, required weekly hours, consecutive lab blocks, A1/A2 labs in parallel)
- Shows the timetable by section, teacher or room in a readable, colour-coded grid
- Prints the timetable or saves it as a PDF

See [docs/requirements.md](docs/requirements.md) for users, roles, the full feature list and the roadmap.

## Run it locally (Windows)
Start the server, then open **http://localhost:8000** and sign in. The server runs the API and serves the app page,
so data is saved and timetables are generated with OR-Tools.

Opening `prototype/index.html` directly (double-click) still works as an offline **demo mode**: demo accounts,
a simple in-browser generator, and nothing is saved.

Backend (API and app on port 8000):
```
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```
On first start it creates a local database (`backend/data/samay.db`) with two demo colleges, each with a coordinator
account and a teacher account. The sign-in page has one-click **demo account** buttons (their passwords are in `backend/data/demo_users.json`).
Turn demo sign-in off for a real launch with `SAMAY_DEMO_LOGIN=0`. To start fresh: `.\.venv\Scripts\python -m app.seed --reset`.

API so far (each signed-in user only ever sees their own college):

| Area | Endpoints |
|---|---|
| Sign-in | `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/signup` (new college), `POST /api/auth/password` |
| Accounts | `GET /api/users`, `POST /api/users` (add a coordinator or a teacher), `DELETE /api/users/{id}` |
| College | `GET /api/college` (summary), `GET /api/college/data` (all data), `PUT /api/college/data` (save; checked again on the server) |
| Pre-check | `GET /api/precheck` |
| Generate | `POST /api/timetables` starts a run (optionally keeping locked classes), `GET /api/jobs/{id}` shows its progress |
| Editing and history | `POST /api/timetables/{v}/revise` (moved or swapped classes), `PUT /api/timetables/{v}/locks`, `POST /api/timetables/{v}/restore`, `DELETE /api/timetables/{v}` |
| Publishing | `POST /api/timetables/{v}/publish` (the version teachers see), `DELETE /api/published` |
| Teachers | `GET /api/teacher` (their record and the published timetable), `PUT /api/teacher/unavailable` (periods they can't teach) |
| Timetables | `GET /api/timetables` (versions), `GET /api/timetables/latest`, `GET /api/timetables/{version}`, `POST /api/timetables/{version}/check`, `POST /api/timetables/{version}/revise` (save an approved change as a new version) |

Coordinators manage everything; teachers only see the published timetable and set when they can't teach.
Every saved timetable has passed the clash checker; each version keeps the data it was built from and is marked
`out_of_date` when data that affects scheduling changes later (renaming a department or changing its status doesn't).
New colleges can sign up from the sign-in page (turn off with `SAMAY_SIGNUP=0`).

Frontend (app on http://localhost:5173):
```
cd frontend
npm install
npm run dev
```

Tests:
```
cd backend
.\.venv\Scripts\python -m pytest
```

## Project structure
```
backend/   app/ (FastAPI app and data schema), solver/ (CP-SAT generator, clash checker, scorecard),
           data/colleges/ (demo colleges), tests/
prototype/ clickable prototype of the whole product (open index.html)
frontend/  React + Vite + TypeScript + Tailwind UI
docs/      requirements and roadmap
```
