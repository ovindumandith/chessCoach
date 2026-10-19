# Implementation Plan

Status key: ✅ done · 🚧 in progress · ⏳ not started

| Phase | Scope | Status |
|---|---|---|
| 1 | Repo, config, DB models, Alembic, health endpoint, Docker Compose | ✅ |
| 2 | Student management and PGN import (aliases, mapping, deduplication, report) | ✅ |
| 3 | Stockfish integration, job worker, persisted move analysis (two-pass) | ⏳ |
| 4 | Skill taxonomy, candidate detectors, coach review endpoints | ⏳ |
| 5 | Longitudinal profiles, Beta-Binomial smoothing, priority heuristic | ⏳ |
| 6 | LLM adapter, evidence retrieval, structured lessons, validation, fallback | ⏳ |
| 7 | Exercises and attempt tracking | ⏳ |
| 8 | Frontend, authentication (JWT + roles), authorization hardening | ⏳ |
| 9 | Research evaluation, end-to-end tests, deployment docs | ⏳ |

## Phase 1 — Foundation

- `pyproject.toml` with pinned dependencies, plus ruff and pytest config.
- `core/config.py`: typed settings loaded from the environment.
- `db/`: portable types, every table from `DATA_MODEL.md`, session factory.
- Alembic environment and initial migration.
- `GET /api/v1/health`: app status plus a database check.
- `docker-compose.yml` (db, backend, worker, frontend placeholder) and Dockerfiles.

## Phase 2 — Students and PGN import

- `POST/GET /api/v1/students`, `GET /api/v1/students/{id}`, and alias management.
- `POST /api/v1/students/{id}/games/import`: multipart upload.
  1. Validate size and encoding.
  2. Compute SHA-256 and store the file by that key.
  3. Parse every game and capture parser errors.
  4. Resolve identity through aliases: `mapped`, `unmatched` or `ambiguous`.
  5. Deduplicate by `game_hash`.
  6. Return an import report: imported, duplicate, rejected and needs-mapping counts with reasons.
- `GET /api/v1/students/{id}/games`: paginated list. `GET /api/v1/games/{id}`.
- `PATCH /api/v1/games/{id}/mapping`: a coach confirms the student and color.
- Audit events for student creation and imports.
- Tests:
  - unit: parser, normalization, game hash, identity resolution
  - integration: multi-game import, duplicate re-import, ambiguous mapping, cross-user access denial

## Phase 3 — Engine analysis (next)

- `analysis/scores.py`: POV normalization, mate handling, a centipawn-loss rule, win-probability loss.
- `analysis/engine.py`: one long-lived `chess.engine.SimpleEngine` per worker, configured from settings, with engine version and checksum recorded.
- `analysis/phase.py`: opening, middlegame or endgame based on material and move number.
- `analysis/worker.py`: claim a queued run, analyze student plies with MultiPV=2, persist idempotently (unique run+ply), retry with bounded attempts.
- Critical-position pass: re-analyze plies above the loss threshold with a larger budget.
- Tests with known positions (marked `engine`), plus pure unit tests for score maths.
