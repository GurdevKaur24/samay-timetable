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
Backend (API on port 8000):
```
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```
On first start it creates a local database (`backend/data/samay.db`) with two demo colleges and one coordinator account
for each; their sign-in details are in `backend/data/demo_users.json`. To start fresh: `.\.venv\Scripts\python -m app.seed --reset`.

API so far: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `GET /api/college`, `GET /api/college/data`.
Each signed-in user only ever sees their own college.

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
