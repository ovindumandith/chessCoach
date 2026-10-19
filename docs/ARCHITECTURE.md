# Architecture

## Shape

The system is a modular monolith. One Python package, `chesscoach`, has two entry points:

- **API** (`uvicorn chesscoach.api.main:app`): FastAPI with thin routes over services.
- **Worker** (`python -m chesscoach.analysis.worker`, Phase 3): polls the PostgreSQL `analysis_runs` job table and runs Stockfish.

The **frontend** (React + TypeScript, Phase 8) talks to the API only.

```mermaid
flowchart TD
    UI[React: coach and student UI] --> API[FastAPI /api/v1]
    API --> SVC[Services]
    SVC --> ING[ingestion]
    SVC --> PRO[profiling]
    SVC --> COA[coaching]
    SVC --> EXE[exercises]
    ING --> FS[(PGN storage by SHA-256)]
    SVC --> DB[(PostgreSQL)]
    W[Analysis worker] --> DB
    W --> SF[Stockfish UCI]
    COA --> LLM[LLM provider adapter]
    COA --> VAL[Chess validation: python-chess + stored evidence]
```

## Data flow

1. **Import.** The PGN is stored under its SHA-256 key. Each game is parsed, validated, mapped to a student through aliases, deduplicated by game hash, and persisted. An import report is returned.
2. **Analyze.** A `POST /games/{id}/analyze` request creates a queued `analysis_runs` row. A worker claims it (`SELECT … FOR UPDATE SKIP LOCKED` on PostgreSQL) and writes `move_analyses`. All scores are normalized to the student's point of view.
3. **Classify.** Move evidence becomes candidate `weakness_observations` tagged with `classifier_version`.
4. **Profile.** Observations, preferring reviewed ones, are aggregated into a new `student_skill_profiles` snapshot version.
5. **Coach.** The latest profile and 2–5 representative positions go into a versioned prompt. The LLM output is validated with Pydantic and then with chess and database checks, and stored as a `coaching_session`.
6. **Practice.** Exercises are drawn from analyzed positions, and attempts are recorded.

## Package layout

```
src/chesscoach/
  core/         config (pydantic-settings), logging, errors
  db/           SQLAlchemy base, portable types, models, session
  api/          FastAPI app, dependencies (auth stub), routes/, schemas
  ingestion/    PGN parsing, identity resolution, storage, import service
  analysis/     engine wrapper, score normalization, features, worker (Phase 3)
  profiling/    taxonomy loading, classifiers, aggregation (Phases 4–5)
  coaching/     provider adapters, retrieval, prompts, validation (Phase 6)
  exercises/    selection and attempts (Phase 7)
  evaluation/   baselines and metrics (Phase 9)
config/         skill_taxonomy.yaml, analysis presets
prompts/        versioned prompt templates
migrations/     Alembic
tests/          unit/, integration/, fixtures/
frontend/       React app (Phase 8)
```

## Key decisions

| Decision | Choice | Why |
|---|---|---|
| Job queue | `analysis_runs` table used as the queue | Enough for a pilot of 30 students, with no extra infrastructure. |
| DB portability | Generic `Uuid`, JSON with a JSONB variant, non-native enums | The same models run on PostgreSQL and in SQLite tests. |
| File storage | Local directory, key = SHA-256 | Idempotent and safe from path traversal. Can be swapped for S3 later. |
| Auth (MVP) | Development stub, then JWT and roles in Phase 8 | `student_access` checks exist in services from the start. |
| LLM | `LLMProvider` protocol with OpenAI-compatible and Anthropic adapters plus a mock | Provider independence and deterministic tests. |
