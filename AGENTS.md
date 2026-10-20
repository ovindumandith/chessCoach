# AGENTS.md — rules for anyone (human or AI) working on ChessMentor AI

The full product specification is in `project.md`; the condensed documents live in `docs/`.
Read `docs/ARCHITECTURE.md` and `docs/IMPLEMENTATION_PLAN.md` before you change code.

## Core design principles (non-negotiable)

| Principle | What it means in code |
|---|---|
| Engine-grounded | Stockfish is the only authority for evaluations and candidate lines. The LLM never computes best moves or legality. |
| Evidence-first | Every weakness observation references a specific `game_id` and `move_analysis_id`. |
| Personalized | Each student has their own profile, history and access controls. |
| Uncertainty-aware | When evidence is thin, return `insufficient_evidence` or `unclassified`, not a confident label. |
| Reproducible | Persist the engine version and config, `analysis_version`, `classifier_version`, taxonomy version and `prompt_version`. |
| Human-reviewable | Rule-derived labels are candidates until a coach confirms them, and `review_status` is always stored. |
| Provider-independent | LLM provider and model are configuration. No chess logic depends on a provider. |
| Privacy-conscious | Every student-scoped route checks `student_access` in the service layer. Don't log PGN content or personal data. |
| Research-ready | Record data splits, baselines and experiment configs. Held-out games never feed profiles or exercises. |
| Incremental | New games update profiles without reprocessing history. Raw PGNs and old analysis runs are immutable. |

## Module boundaries

- `ingestion/` parses and stores PGNs. It never calls the engine or the LLM.
- `analysis/` runs Stockfish and computes move features. It never writes coaching text or profiles.
- `classification/` turns stored engine evidence into candidate observations and skill opportunities, and handles coach review. It reads analysis rows only and never calls the engine.
- `profiling/` aggregates observations into versioned snapshots. It never treats unreviewed candidates as ground truth.
- `coaching/` retrieves evidence, calls the LLM and validates output. Only this module talks to the LLM.
- `exercises/` handles exercise selection and attempts.
- `evaluation/` holds research baselines and metrics. Keep it separate from live services.
- `api/` holds thin routes. Business logic lives in services, not route handlers.
- `db/` holds models, session and types. Schema changes always go through an Alembic migration.

## Chess-correctness rules

- Normalize every evaluation to the **student's** perspective (`PovScore.pov(student_color)`).
- Store mate scores separately (`*_mate` columns). Never silently convert a mate score to centipawns.
- Only compute centipawn loss when both scores are ordinary centipawn values.
- Only the student's own moves count toward move-quality statistics.
- A high evaluation loss alone does not justify a motif or skill label. Engine-confirmed errors with no verified cause are stored as `unclassified`.
- Motifs are reported only when the board check (python-chess) **and** the engine evidence agree.
- Reclassification never deletes or duplicates coach-reviewed observations.

## Engineering rules

- Target Python 3.11+ (local dev currently runs 3.14). Pin dependencies in `pyproject.toml`.
- Models must work on PostgreSQL (production) and SQLite (fast local tests). Use the portable types in `db/types.py`.
- Use UUID primary keys and UTC timestamps (`db.types.utcnow`).
- Enums are string-backed (`native_enum=False`) so migrations stay simple.
- Never run long Stockfish work inside a request handler. Queue a job and let the worker run it.
- Never create tables at app startup in non-test code. Use `alembic upgrade head`.
- After every new migration, run upgrade, downgrade and upgrade on SQLite, run `alembic check`, and render the PostgreSQL SQL (`alembic upgrade <prev>:head --sql`).
- SQLite batch mode has two known quirks:
  - Adding an enum column creates its CHECK constraint twice (enum name plus naming convention).
  - Dropping the column keeps the CHECK, which breaks the downgrade.
  - Fix: drop both names first, wrapped in `batch_op.f()`, on SQLite only. See `*_exercise_lifecycle.py`.
- Adding NOT NULL columns to a table that may hold data needs a guard or a backfill. Never invent values.
- Secrets come only from environment variables. Never commit `.env` or API keys.
- Uploaded files are stored by SHA-256 key, never by the user-supplied filename.
- The unit suite must run without Docker, a live LLM key or Stockfish. Mark engine tests with `@pytest.mark.engine`.

## Workflow for each phase

1. State the intended changes.
2. Implement a small, coherent change set.
3. Run `ruff check` and `pytest`, and fix failures before moving on.
4. Update the relevant `docs/` file.
5. Report changed files, test results and open issues honestly. Never claim untested behavior works.
