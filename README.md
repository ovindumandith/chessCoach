# ChessMentor AI

ChessMentor AI is a personalized chess coaching platform. It analyzes students' PGN games with Stockfish, builds evidence-backed and versioned skill profiles, and uses an LLM to explain verified findings and set targeted practice.

- Full specification: [`project.md`](project.md)
- Rules for contributors and agents: [`AGENTS.md`](AGENTS.md)
- Design documents: [`docs/`](docs/), including the architecture, data model, research plan and implementation plan

**Status:** Phases 1–6 are done: foundation, students and PGN import, Stockfish analysis, weakness classification with coach review, versioned student profiles, and LLM coaching with validation. See [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).

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

This starts:
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

Until Phase 8 adds authentication, requests run as a development coach account. To act as another existing user in development, send the `X-Dev-User-Email` header. This stub refuses to run when `APP_ENV=production`.

## Tests and linting

```bash
pytest                 # unit + integration; needs no Docker, LLM key or Stockfish
pytest -m engine       # only the real-Stockfish tests (skipped if STOCKFISH_PATH is not set)
ruff check src tests && ruff format --check src tests
```

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
