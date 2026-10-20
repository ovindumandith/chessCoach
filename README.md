# ChessMentor AI

ChessMentor AI is a personalized chess coaching platform. It analyzes students' PGN games with Stockfish, builds evidence-backed and versioned skill profiles, and uses an LLM to explain verified findings and set targeted practice.

- Full specification: [`project.md`](project.md)
- Rules for contributors and agents: [`AGENTS.md`](AGENTS.md)
- Design documents: [`docs/`](docs/), including the architecture, data model, research plan and implementation plan

**Status:** All nine phases of the MVP are done: PGN import, Stockfish analysis, weakness classification with coach review, versioned profiles, LLM coaching with validation, exercises, login with roles, the React interface, research evaluation, browser end-to-end tests, and operations procedures.

Running it for real? Read [`docs/OPERATIONS.md`](docs/OPERATIONS.md) for the production checklist, backups, restores and data deletion. See [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).

## Quick start: local, without Docker

You need Python 3.11+ and, from Phase 3 on, a Stockfish binary.

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows. On macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env              # then edit:
#   DATABASE_URL=sqlite:///./data/chesscoach.db
#   STOCKFISH_PATH=<path to stockfish executable>
#   STORAGE_DIR=./data/uploads

mkdir -p data
alembic upgrade head              # create or upgrade the schema (never auto-created at startup)
uvicorn chesscoach.api.main:app --reload
```

Interactive API docs are at http://localhost:8000/docs.

SQLite is for local development only. Production uses PostgreSQL.

## Quick start: Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Then create the first administrator. There are no default accounts:

```bash
docker compose exec backend python -m chesscoach.bootstrap --email you@example.org
```

Open http://localhost:8080 and sign in. Then:
1. Create coach accounts (`POST /api/v1/users`, admin only).
2. Coaches add students and give each student a login from the student's **Account** tab.
3. Students sign in, add and analyze their own games, go through their mistakes game by game, and get AI training recommendations and exercises. Coaches monitor: each student's games, mistakes and recommendations, plus the mistakes across all their students.

This starts:
- `frontend`: the React app served by nginx on port 8080, which proxies `/api` to the backend
- `db`: PostgreSQL 16
- `migrate`: runs `alembic upgrade head` once
- `backend`: the API on port 8000
- `worker`: the analysis worker, running official Stockfish 18 (checked by SHA-256)

The volumes `pgdata` and `uploads` persist data. Never run `docker compose down -v` unless you mean to delete all student data.

## Try it

```bash
# Create a student, with the PGN names they play under
curl -X POST localhost:8000/api/v1/students -H "Content-Type: application/json" \
  -d '{"display_name": "Ovindu", "aliases": ["Ovindu", "ovindu_m"]}'

# Import a PGN file. The response is an import report.
curl -X POST localhost:8000/api/v1/students/<id>/games/import -F "file=@tests/fixtures/mixed_games.pgn"

# List games still waiting for a coach to confirm the student's color
curl "localhost:8000/api/v1/students/<id>/games?needs_mapping=true"

# Confirm one of them
curl -X PATCH localhost:8000/api/v1/games/<game_id>/mapping -H "Content-Type: application/json" \
  -d '{"student_color": "white"}'

# Queue Stockfish analysis (needs a confirmed color), then poll and read the results
curl -X POST localhost:8000/api/v1/games/<game_id>/analyze
curl localhost:8000/api/v1/analysis-jobs/<job_id>
curl localhost:8000/api/v1/games/<game_id>/analysis
```

## LLM coaching

Lessons are generated from the student's profile and stored engine evidence. LLM output is shown only after chess and evidence validation. Otherwise a deterministic template lesson is returned, so coaching keeps working without an LLM.

```bash
# .env
LLM_ENABLED=true
LLM_PROVIDER=anthropic        # or openai_compatible (+ LLM_BASE_URL)
LLM_MODEL=claude-opus-5-5
# LLM_API_KEY=...             # or leave empty to use ANTHROPIC_API_KEY / an `ant auth login` profile

curl -X POST localhost:8000/api/v1/students/<id>/coaching/lessons
```

## Running the analysis worker locally

Without Docker, set `STOCKFISH_PATH` in `.env` and run:

```bash
python -m chesscoach.analysis.worker
```

The worker runs one Stockfish process. For more throughput, run more worker processes (`docker compose up --scale worker=2`). On PostgreSQL, jobs are claimed with `SKIP LOCKED`, so two workers never take the same game. Keep `STOCKFISH_THREADS=1` for reproducible research runs.

## Authentication

Every API request needs `Authorization: Bearer <token>` from `POST /api/v1/auth/login`. The roles are:
- **admin**: everything, including creating coach accounts
- **coach**: only the students they created or were given
- **student**: their own record only, and the only role that may answer exercises

For quick local API experiments, `AUTH_DEV_BYPASS=true` (development only) accepts an `X-Dev-User-Email` header instead. It is always off in production, and the curl examples above assume it is on.

## Frontend development

```bash
cd frontend
npm ci --ignore-scripts
npm run dev        # http://localhost:5173, proxies /api to localhost:8000
npm run build      # type-check and production build
```

## Tests and linting

```bash
pytest                 # unit + integration; needs no Docker, LLM key or Stockfish
pytest -m engine       # only the real-Stockfish tests (skipped if STOCKFISH_PATH is not set)
ruff check src tests && ruff format --check src tests
```

## Analysing your games

1. Sign in as a coach and add a student, with **PGN player names** set exactly as they appear in your PGN files. On the student's **Account** tab, create their login.
2. Sign in as the student. In **My games**, upload a PGN, then click **Analyze all**. The list updates by itself while Stockfish works.
3. Open **View** for a game:
   - every move shows the stored Stockfish verdict
   - a **live engine** runs in your browser
   - you can drag pieces to explore lines
   - mistakes you've made before link to those earlier games
4. As the student: **My mistakes** lists each analyzed game's mistakes with the reason and the better move. **Acknowledge** each one; if you repeat a kind of mistake you acknowledged before, it's flagged "again". **Exercises** shows the AI coach's recommendation, and **Practise this** builds exercises from your own positions.
5. As the coach: the student list shows each student's activity and open mistakes, **Mistakes across students** groups mistakes over all your students, and each student's **Mistakes** and **Recommendations** tabs show what they see, read-only.

## End-to-end tests

A browser drives the real UI against the running stack: the coach creates a student and their login → the student adds and analyzes games, acknowledges a mistake, gets the AI recommendation and solves an exercise by dragging a piece → the coach monitors activity, the student's mistakes and recommendations, and the mistakes across students.

```bash
docker compose up -d
cd frontend
E2E_ADMIN_EMAIL=you@example.org E2E_ADMIN_PASSWORD=... npm run e2e
```

The tests use the system Chrome by default. `PW_CHANNEL=msedge`, or `PW_CHANNEL=chromium` after `npx playwright install chromium`, selects another browser.

## Research evaluation

`python -m chesscoach.evaluation <study> config/experiments/pilot_v1.yaml` covers:
- a blind annotation sheet and classifier benchmark
- coach-review precision
- predictive validity of profiles against a population baseline
- a blinded A/B/C coaching comparison

Each run writes a reproducible record to `data/experiments/`. See [`docs/OPERATIONS.md`](docs/OPERATIONS.md#research-workflow).

## Database migrations

```bash
alembic revision --autogenerate -m "describe change"   # review the generated file
alembic upgrade head
```

`tests/integration/test_migrations.py` fails if the models and the migrations drift apart.

## Backups

For PostgreSQL in Docker:

```bash
# Back up
docker compose exec db pg_dump -U chesscoach chesscoach > backup.sql

# Restore
docker compose exec -T db psql -U chesscoach chesscoach < backup.sql
```

Also back up the `uploads` volume, which holds the original PGN files keyed by SHA-256.
