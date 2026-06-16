# bst-data-collection-platform

Local-first web app for an in-person, robot-mediated BST/DTT human-robot
interaction study. One experimenter runs a full session; a participant tablet
collects self-reports; a server-attached camera records raw A/V; behavioral
signals are ingested from an existing HRI perception platform. Every session is
unrepeatable, so zero data loss and raw-data immutability are paramount.

See `docs/` for the governing specs (`product_plan.md`, `PRD.md`,
`requirements.md`, `perception_integration.md`) and `CLAUDE.md` for the hard
rules.

## Stack

- Backend: Python FastAPI + SQLite (SQLAlchemy 2.0)
- Frontend: React + Vite (added in a later phase)
- Local file storage for recordings, exports, logs, session timelines
- YAML/JSON configs for questionnaires, DTT protocols, study conditions
- No Docker for v1 (plain processes; `.env` keeps containerizing easy later)

## Status

Phase 1 (Day 1, P0.1): backend skeleton with all 21 data models, server
starts, tables migrate, CRUD verifiable via `/docs`.

## Backend: setup and run

All paths and ports come from `.env` (copy from `.env.example`). Defaults:
API on `:8080`, frontend origin `:5173`, perception orchestrator `:8000`.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# from the backend/ directory, with the venv active:
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Then open:

- `http://<host>:8080/` — service info
- `http://<host>:8080/health` — liveness
- `http://<host>:8080/docs` — interactive API docs (Swagger UI)

On startup the app creates the data directories and all tables in the SQLite
database at `DB_PATH` (default `data/bst.db`). `create_all` is idempotent.

## Data model

21 tables (16 P0-active, 5 defined-but-unused as P1/P2 insurance). See the
session history / schema design for the full table list and rationale. Hard
rules enforced by design:

- Raw records are never overwritten; corrections/exclusions/scoring are rows in
  `annotations` or derived tables.
- Participant IDs only in research tables; no names (`participant_identity`
  exists but is unwritten in v1).
- Every significant event also writes a `session_timeline_events` row
  (UTC + `session_time_ms`).

## Repository layout

```
backend/
  app/
    api/        # routers (health, participants, ...)
    core/       # config (.env), time helpers
    db/         # engine, session, metadata
    models/     # SQLAlchemy models (21 tables)
    schemas/    # Pydantic request/response models
    main.py     # FastAPI app + lifespan (create dirs + tables)
  tests/
  requirements.txt
configs/        # questionnaires, dtt_protocols, study_conditions
data/           # recordings, exports, logs, sessions, bst.db (gitignored)
docs/           # governing specs
.env.example
```
