# Implementation Plan

Status key: ✅ done · 🚧 in progress · ⏳ not started

| Phase | Scope | Status |
|---|---|---|
| 1 | Repo, config, DB models, Alembic, health endpoint, Docker Compose | ✅ |
| 2 | Student management and PGN import (aliases, mapping, deduplication, report) | ✅ |
| 3 | Stockfish integration, job worker, persisted move analysis (two-pass) | ✅ |
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

## Phase 3 — Engine analysis

- `analysis/scores.py` (`scores-v1`):
  - Every evaluation is from the **student's** side.
  - Mate scores are kept separate from centipawns.
  - Centipawn loss is computed only when both scores are centipawns.
  - Win-probability loss uses the Lichess logistic model and is always defined.
  - Mate transitions are labeled explicitly: `missed_mate`, `allowed_mate`, `mate_to_mated` and others.
  - If the student played the engine's top move, loss is zero (search noise is not a decision error).
- `analysis/phase.py` (`phase-v1`): a simplified version of Lichess's Divider. Endgame means 6 or fewer minor and major pieces. Opening means move 12 or earlier with more than 10 minor and major pieces.
- `analysis/engine.py`: one long-running Stockfish process per worker. Name, version and binary SHA-256 are recorded on every run. `ucinewgame` is sent between games so hash contents never carry over.
- `analysis/game_analyzer.py` (`analysis-v1`):
  - Two engine calls per student move: MultiPV=2 before, MultiPV=1 after.
  - Positions after checkmate, stalemate or insufficient material are scored from the rules, because the engine's `Mate(-0)` loses its sign.
  - Records clocks, material, check and capture flags, the gap to the second-best line (to spot only-moves), and the main line in SAN (checked for legality).
- `analysis/worker.py`:
  - Claims jobs with `FOR UPDATE SKIP LOCKED`.
  - Retries are idempotent: a run's rows are replaced, never duplicated.
  - Attempts are bounded, then the job is marked `failed`.
  - Jobs left running by a crashed worker are reclaimed.
  - A dead engine is restarted.
  - Once the baseline finishes, a `critical` pass is queued that re-analyzes only the critical plies at `STOCKFISH_CRITICAL_DEPTH`.
- API:
  - `POST /games/{id}/analyze` returns 202 for a new job and 200 when an existing one is reused. `{"force": true}` re-runs. Games without a confirmed color get 409.
  - `GET /analysis-jobs/{id}`
  - `GET /games/{id}/analysis` returns the baseline moves plus the critical-pass moves.
- Docker: the worker uses official Stockfish 18 (`sf_18`, AVX2), checked by SHA-256 at build time. It defaults to 1 thread, because multi-threaded search is non-deterministic.
- Tests:
  - unit: scores, phase, and the game analyzer with a deterministic `FakeAnalyzer`
  - integration: queue, worker, API, retries, crash reclaim, access control
  - `engine` tests against real Stockfish
- Verified end to end on PostgreSQL in Docker with real Stockfish 18.

### Known limitations and Phase 4 inputs

- Only the student's moves are analyzed. Opponent mistakes the student failed to punish ("missed opportunities") need the opponent's moves analyzed too, which is planned with the motif detectors.
- Evaluations are single searches at a fixed depth. Stability across repeated or deeper searches is only checked for critical plies.
- The critical threshold (10% win-probability loss) is an untested default. Calibrate it against coach labels.

## Phase 4 — Taxonomy, detectors, coach review (next)

- `config/skill_taxonomy.yaml` (versioned), including `unclassified` and `insufficient_evidence`.
- v1 rules: move-quality evidence from win-probability loss, phase, and only-move gap. v2: a few verifiable motif detectors (hanging piece, fork, missed mate in N) checked with python-chess.
- `weakness_observations` keep move-quality, motif and skill-inference evidence separate, each with `classifier_version`.
- Coach review endpoints: confirm, reject or correct, with audit events.
