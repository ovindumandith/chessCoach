# Implementation Plan

Status key: ✅ done · 🚧 in progress · ⏳ not started

| Phase | Scope | Status |
|---|---|---|
| 1 | Repo, config, DB models, Alembic, health endpoint, Docker Compose | ✅ |
| 2 | Student management and PGN import (aliases, mapping, deduplication, report) | ✅ |
| 3 | Stockfish integration, job worker, persisted move analysis (two-pass) | ✅ |
| 4 | Skill taxonomy, candidate detectors, coach review endpoints | ✅ |
| 5 | Longitudinal profiles, Beta-Binomial smoothing, priority heuristic | ✅ |
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

## Phase 4 — Taxonomy, detectors, coach review

- `config/skill_taxonomy.yaml` (`taxonomy-v1`): 8 categories and 34 subskills, plus `unclassified` and `insufficient_evidence`. Each subskill is marked with whether classifier-v1 can produce it automatically. Opening knowledge is deliberately never inferred automatically.
- `classification/motifs.py` (`motifs-v1`): python-chess checks for forks, hanging pieces and mates.
  - Applied to the engine's best move (*missed*) and to the engine's best reply (*allowed*).
  - Uses legal moves only, so pinned pieces can't capture.
  - Pawns are excluded as targets.
- `classification/classifier.py` (`classifier-v1`):
  - Severity bands use Lichess-style win-probability thresholds.
  - Forced moves are skipped.
  - A motif is reported only when the engine says it mattered.
  - Skill-inference rules cover: error in an endgame (low confidence), error while winning, missed only move, and error in time trouble.
  - Anything left unexplained is stored as `unclassified`.
- Skill opportunities record where a tactic was available **and needed** (gap to the second-best line ≥ 0.08), with the outcome converted or missed. These are the denominators for Phase 5 error rates.
- `analysis-v2` stores the engine's best reply to each student move, which is needed for *allowed* motifs.
- Classification runs automatically after the final analysis pass. Re-running it is idempotent and keeps reviewed rows.
- API:
  - `GET /taxonomy`
  - `POST /games/{id}/classify`
  - `GET /students/{id}/weaknesses`, filterable, with the move evidence attached
  - `PATCH /observations/{id}/review` to confirm, reject or correct, with an audit trail
  - Students never see rejected findings and cannot review.
- Verified end to end with real Stockfish 18 on PostgreSQL, using the Blackburne Shilling trap.

### Known limitations and Phase 5 inputs

- Detectors don't yet cover pins, skewers, discovered attacks, or double attacks on a pawn plus a piece. 4…Qg5 in the Blackburne trap stays `unclassified`.
- Opportunity rows exist only for "missed" motifs. For "allowed" motifs, the denominator in Phase 5 is the number of analyzed moves.
- All thresholds are untested defaults. The coach-review data is the benchmark for tuning them.

## Phase 5 — Longitudinal profiles

- `profiling/aggregator.py` (`profile-v1`, pure functions). Each skill is measured through up to two **channels**, never mixed in one ratio:
  - *detected*: Phase 4 opportunities, i.e. tactics available **and needed**. An error is a missed one.
  - *exposure*: moves in the relevant context. That's every move for allowed tactics and for `unclassified`, endgame moves of the matching type, moves while winning, only-move defensive positions, and time-trouble moves. Forced moves are excluded.
  - The context rules are shared with the classifier (`is_time_trouble`, `endgame_type`), so error counts and denominators always agree.
- **Rates:** Beta-Binomial `p = (e+a)/(n+a+b)`, with priors per channel (detected 1/2, exposure 0.5/24.5). Confirmed or corrected findings count 1, candidates 0.5, rejected 0. A rejected or relabelled missed motif also removes its opportunity.
- **Priority:** `P = E×S×R×C`.
  - E is the rate relative to the channel's reference.
  - S is mean severity relative to 0.30.
  - R is distinct games affected, capped at 4.
  - C is the data share of the posterior, `n/(n+a+b)`.
  - Only channels with data drive the score, because an empty channel's prior mean must not outrank real data.
  - Skills labelled only by coaches use `0.5×S×R`.
  - `unclassified` is never ranked. It's a review queue, not a trainable skill.
- **States:**
  - *recurring weakness*: 3 or more games and E ≥ 0.3
  - *emerging pattern*: 2 or more games
  - *insufficient evidence*: a single affected game, or too little data
  - *no issue detected*: at least 3 games and 5 exposures with no errors
- Each skill summary also records: `provisional` (mostly unreviewed), `needs_diagnostic` (some channel has fewer than 5 observations, so the exploration rule applies), recent errors, the change from the previous version, and up to 5 example observations, one per game, for Phase 6 retrieval.
- **Snapshots** (`profile_snapshots` with skill rows):
  - A fingerprint over all evidence and reviews means a new version is created only when something changed.
  - History is kept.
  - The worker rebuilds after each classification.
  - `cutoff_date` builds use only earlier games, for research hygiene.
- **Classifier v2:**
  - A missed capture is not reported if the student's own move captured at least as much. Found on Legal's Mate, where …Bxd1 takes the queen.
  - **Coach reviews carry forward across classifier versions**, matched on ply, skill and evidence type, so they survive both version bumps and re-analysis.
  - The weaknesses list shows the current version only.
  - `python -m chesscoach.classification.reclassify` reclassifies everything and rebuilds profiles.
- API:
  - `GET /students/{id}/profile` returns skills ordered by priority with unranked ones last, plus a `stale` flag.
  - `POST /students/{id}/profile/rebuild` accepts an optional `cutoff_date`.
  - `GET /students/{id}/profile/history`
- Verified end to end on PostgreSQL with real Stockfish 18 over four trap games. Mating patterns came out as a recurring weakness across 3 games: one missed mate and two allowed mates.

### Known limitations and Phase 6 inputs

- Every parameter is an untested default. The cutoff snapshots exist so predictive validity can be measured in Phase 9.
- Exposure rates for allowed tactics use every move as the denominator, which is coarse. A "had a piece that could be hung" denominator would be sharper.
- Exercise accuracy enters profiles in Phase 7. Until then the profile reflects game evidence only.

## Phase 6 — LLM coaching (next)

- Provider abstraction (OpenAI-compatible and Anthropic adapters, plus a mock), configured through env.
- Evidence retrieval from the latest profile: the top actionable skills and 2–5 example positions from different games.
- Versioned prompt `prompts/chess_coach_v1.txt` and Pydantic output.
- Chess validation of the output (game ownership, FEN and ply match, legal moves, engine claims), with a deterministic template fallback.
