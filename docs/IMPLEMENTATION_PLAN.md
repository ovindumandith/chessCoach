# Implementation Plan

Status key: ✅ done · 🚧 in progress · ⏳ not started

| Phase | Scope | Status |
|---|---|---|
| 1 | Repo, config, DB models, Alembic, health endpoint, Docker Compose | ✅ |
| 2 | Student management and PGN import (aliases, mapping, deduplication, report) | ✅ |
| 3 | Stockfish integration, job worker, persisted move analysis (two-pass) | ✅ |
| 4 | Skill taxonomy, candidate detectors, coach review endpoints | ✅ |
| 5 | Longitudinal profiles, Beta-Binomial smoothing, priority heuristic | ✅ |
| 6 | LLM adapter, evidence retrieval, structured lessons, validation, fallback | ✅ |
| 7 | Exercises and attempt tracking | ✅ |
| 8 | Frontend, authentication (JWT + roles), authorization hardening | ✅ |
| 9 | Research evaluation, end-to-end tests, deployment docs | ✅ |

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

## Phase 6 — LLM coaching

- **Providers** (`coaching/providers.py`) sit behind one `LLMProvider` interface:
  - `AnthropicProvider` uses the official SDK (`anthropic==1.15.0`), default model `claude-opus-5-5`.
    - Structured output through `output_config.format` (strict JSON Schema) at configurable `effort` (default `medium`).
    - Server-side refusal fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`).
    - Refusal and `max_tokens` stops are treated as failures.
    - Usage, latency, request id, and whether a fallback model served the request are all recorded.
  - `OpenAICompatibleProvider` uses plain HTTP with `json_schema` response formats and bounded retries on 429 and 5xx.
  - `MockProvider` serves tests.
  - **LLM calls are opt-in** (`LLM_ENABLED=false` by default).
- **Retrieval** (`coaching/retrieval.py`) builds the context from the latest live profile:
  - the top *actionable* skill (`unclassified` is never chosen, even from older snapshots) and the secondary skill
  - up to 5 positions from different games, using the profile's examples first, with deeper critical-pass evidence where available
  - previous lessons
  - It never sends the whole archive. Each position holds stored facts only: FEN, played move, engine line, opponent's best reply, and evaluations from the student's side.
- **Prompt** `prompts/chess_coach_v1.txt` is versioned and recorded on every session. Its grounding rules come from project.md §20.
- **Output** (`CoachingResponse`) routes checkable claims into structured fields: game_id, ply, FEN, the engine's best move, and separate lists for facts and hypotheses.
- **Validation** (`coaching/validation.py`) checks, beyond Pydantic:
  - the skill matches the objective, with 1–2 examples
  - every example is a supplied position with an exact FEN match
  - a claimed engine move is legal **and** equals the stored one
  - every SAN move in free text appears in the evidence (bare pawn pushes are skipped, since they read like squares)
  - every quoted evaluation or "mate in N" matches stored values
  - the student question doesn't reveal the solution
  - a database check that every referenced game belongs to the student
- **Flow:** generate → validate → one regeneration with the rejection reasons → otherwise a **deterministic template lesson** built from the same evidence (`template-v2` since findings stopped being reviewed). The template is itself validated before anything is returned.
- **Every request** is stored as a `coaching_sessions` row: provider and model, prompt version, evidence references, context hash, every attempt with its errors, token usage, and latency. An audit event is written too.
- **API:** `POST /students/{id}/coaching/lessons` (optional `skill_code`) and `GET /students/{id}/coaching/sessions`. Students can request their own lessons.
- Verified on PostgreSQL with real Stockfish evidence through the template path. Not yet run against a live LLM, because no credentials are configured.

### Known limitations and Phase 7 inputs

- Free-text checks are pattern-based. Prose like "the knight sacrifice" isn't checked. Structured fields are the strong guarantee.
- No rate limiting on lesson generation yet (Phase 8 security).
- `exercise_history` is empty until Phase 7.

## Phase 7 — Exercises

- **Selection** (`exercises/selection.py`, `exercise-selection-v1`) draws positions from the student's analyzed games, using deeper critical-pass evidence where available. A position qualifies only when its solution is **unambiguous** by the stored engine evidence:
  - a forced mate, or a best move at least 0.15 win probability ahead of the second-best line
  - at least 3 legal moves
  - the stored best move is legal
  - For mate-in-1, *every* checkmating move is accepted, verified by the rules.
- **Relevance per skill:**
  - tactics: the motif is present in the solution
  - endgames: phase and endgame type
  - conversion: the student is winning
  - finding resources: an only-move defence
  - coach-labelled skills: positions where an observation names the skill
- **Purposes:**
  - *review*: positions where the student went wrong on that skill, ordered by severity
  - *practice*: other qualifying positions from their games
  - Positions are never reused for the same student.
  - `practical_play.time_management` and `unclassified` are not board exercises (409).
- **Lifecycle:**
  - open → solved, failed (after 3 attempts), or revealed (gave up)
  - Solutions are hidden until the exercise is finished.
  - Three progressive hints: the theme, then the piece, then the square. The theme hint matches attack or defence, because a position where the student *allowed* a mate is a defensive task.
  - Attempts accept UCI or SAN. Illegal moves get 422 and are **not recorded**.
  - Only the student's own account may answer, hint or reveal, so coach activity never pollutes the data.
- **Outcomes:**
  - `GET /students/{id}/progress` shows first-try accuracy per skill next to the profile trend across snapshot versions.
  - Profiles carry exercise accuracy in each skill summary, but it is **informational only** (`affects_priority: false`, project.md §11).
  - Exercise history (outcomes only, never solutions) now fills the coaching context.
- **API:** `POST/GET /students/{id}/exercises`, `GET /exercises/{id}`, `POST /exercises/{id}/hint`, `POST /exercises/{id}/attempts`, `POST /exercises/{id}/reveal`, `GET /students/{id}/progress`.
- Verified on PostgreSQL with real Stockfish 18 evidence.
  - Review exercise: the missed Qxf7#. Practice exercise: the game where Qxf7# was found.
  - The 7.Be2 position (2 legal moves) and the 5…Bxd1 position (no unique solution) were correctly excluded.

### Known limitations

- Single-move exercises only. Multi-move puzzles would need the full solution line validated move by move.
- No "avoid the blunder" exercise type yet. In Legal's Mate the lesson is "anything but …Bxd1", which a unique-solution puzzle can't express.
- No exercises from unseen positions yet, which research-grade pre/post measurement needs. A themed puzzle bank (for example the CC0 Lichess puzzle database) is the natural source, and it's a decision for you to make.
- Difficulty labels are heuristics from the mate distance or best-move margin.

## Phase 8 — Authentication, authorization, frontend

**Backend security**
- Passwords use stdlib `scrypt` (N=2^14, r=8, p=1, per-user salt, constant-time compare), with a minimum length of 10.
- Access tokens are HS256 JWTs via PyJWT, 60 minutes by default. `sub`, `exp` and `iat` are required, and `alg=none` and other keys are rejected.
- `POST /auth/login`: emails are normalized, unknown emails and wrong passwords get identical responses and timing, and every attempt is audited.
- Other account endpoints:
  - `GET /auth/me`, with the accessible students
  - `POST /auth/change-password`
  - `POST /users`: admin only, creates coach or admin accounts
  - `POST /students/{id}/account`: a coach creates a login for their own student, with SELF access, one per student
- `python -m chesscoach.bootstrap` creates the first admin. There are no default credentials.
- The `X-Dev-User-Email` stand-in is accepted only in `test`, or in `development` with `AUTH_DEV_BYPASS=true`. Production also **refuses to start** without a strong `APP_SECRET_KEY`.
- **Rate limits** (in-memory sliding window, per user per hour): lessons, analysis requests, exercise creation and PGN imports. Logins are limited per email and IP (10 per 15 minutes), which returns 429 with `retry_after_seconds`.
- CORS allows only configured origins, with no cookies. The Docker frontend is same-origin through nginx.

**Frontend** (`frontend/`: React 19, TypeScript strict, Vite 8, react-chessboard 5, chess.js 1, react-router 7; exact versions at least two weeks old, installed with `--ignore-scripts`)
- **Coach** (superseded by the role split in Post-MVP additions: coaches now monitor, students add games and get lessons). Originally: student list and creation, and per student seven tabs:
  - Games: PGN import with the report, colour confirmation, Analyze
  - Review findings: a board with played and engine-best arrows, confirm, reject, or correct against the taxonomy
  - Profile: states, rates, priority, exercise accuracy, rebuild and stale flag
  - Lessons: generate, with history and the source shown (LLM or template)
  - Exercises
  - Progress
  - Account: create the student's login
- **Game viewer:** every student move with evaluation before and after, the engine line, the opponent's best reply, and big losses flagged. Deeper critical-pass evidence replaces the baseline.
- **Student:** exercises (drag a piece or type SAN, progressive hints, give up, solution and "what you played in the game" afterwards), lessons, own profile, progress, own games.
- Tokens are kept in `sessionStorage` and sent as Bearer tokens, never as cookies. A 401 signs the user out. Every page has loading, empty and error states, and both light and dark themes are supported.
- **Docker:** a `frontend` service (a Node build stage, then nginx with security headers and an SPA fallback) proxies `/api` to the backend on port 8080.

**Verified**
- 236 backend tests pass. `tsc --noEmit` and `vite build` succeed.
- End to end through nginx with real Stockfish 18 on PostgreSQL:
  - The admin bootstraps, then creates a coach.
  - The coach sees only their own students.
  - The coach creates a student, imports a PGN and gives the student a login.
  - The student can reach only their own record (403 elsewhere, and on creating students or importing).
  - The student solves a practice exercise from their own game.
- **Not yet done:** clicking through the UI in a real browser. Automated browser tests come in Phase 9.

### Known limitations

- Rate limits and the login throttle are per process. Several backend processes need a shared store such as Redis.
- There are no refresh tokens: users sign in again after 60 minutes, and tokens can't be revoked before they expire (deactivating a user blocks them on the next request).
- Admin user management has an API but no screen yet.

## Phase 9 — Research evaluation, end-to-end tests, operations

**Data deletion** (`privacy.py`; `DELETE /students/{id}?confirm=<name>` for the coach; `python -m chesscoach.privacy delete-student`)
- Deletes in explicit dependency order, because evidence foreign keys deliberately don't cascade.
- PGN files are kept while another student's games still use them.
- The student's own login is anonymized and deactivated. Audit events hold no names.
- Verified on SQLite and on PostgreSQL: zero orphaned analysis runs, and a wrong confirmation name is refused.

**Evaluation** (`evaluation/`, `python -m chesscoach.evaluation`; read-only against live tables)
- **Benchmark:**
  - a *blind*, stratified annotation sheet: flagged and unflagged moves, engine facts only, no classifier labels
  - scoring of the classifier's *original* labels (before review): per-label precision, recall, F1 and macro-F1, plus critical-move detection
  - Labels that are only ever predicted count as F1 = 0. A unit test caught an early version that silently dropped them, which flattered the classifier.
- **Review precision:** confirmed ÷ reviewed per label, explicitly labelled precision-only and non-blind.
- **Predictive validity:**
  - pre-cutoff profiles are built in memory (no snapshots written) and their top-k actionable skills are compared with skills that occur in post-cutoff games
  - compared against a non-personalized population baseline, P@k per student and on average
- **Coaching comparison:**
  - per student: A (engine-only critical moves), B (template), C (validated LLM lesson, only if enabled)
  - shuffled under neutral names, with a CSV rating sheet (five criteria, 1–5) and a separate key file
  - `coaching-score` joins the ratings with the key
- **Records:** every run writes JSON with the code revision (git, or `CHESSCOACH_REVISION` baked into the image), every component version, non-secret settings, seed, config and dataset IDs, to `EXPERIMENTS_DIR`.
- Run inside Docker on real data. `predictive`, on the four trap games with a cutoff between game 2 and game 3, predicted mating patterns and threat prevention, and both recurred. With one student, the baseline is identical, so this is a plumbing check, not evidence.

**Browser end-to-end** (`frontend/e2e/`, Playwright 1.63, system Chrome)
- One continuous journey: the admin creates a coach through the API. In the UI, the coach:
  - creates a student and imports a PGN
  - runs the real Stockfish analysis
  - inspects the game viewer
  - confirms a finding on the board
  - rebuilds the profile and generates a lesson
  - creates the student's login

  The student then signs in, takes a hint, makes an illegal drag (rejected, nothing recorded), solves Qxf7# **by dragging the queen**, sees the solution, and can't reach coach pages.
- Passed 3 of 3 runs (19–23 s).

**Operations** (`docs/OPERATIONS.md`): first start, production checklist, backup, restore, deletion, upgrades and reclassification, LLM enablement, troubleshooting, and the research workflow.
- The backup and restore round trip was **verified**: the restored copy matched the live database exactly (row counts and migration head), and the uploads archive contained all files.

### Post-MVP additions

- **Live engine in the browser:**
  - Stockfish 19 lite (stockfish.js, single-threaded WASM, GPLv3; the licence and source are linked in the UI) runs in a Web Worker in the game viewer.
  - It shows MultiPV 3 with a depth counter and an evaluation bar from the student's side.
  - **Explore mode** lets you drag pieces to try lines, with "back to the game" to return.
  - It is exploration only. Nothing it computes is stored, and profiles keep using the pinned, fixed-depth server analysis (Stockfish 18).
  - Stale-search safety: a new position waits for the previous search's `bestmove`, so old lines never appear against a new position.
- **"You made the same mistake here before":**
  - `GET /games/{id}/findings` links each finding to the same mistake in the student's other games.
  - Same mistake = same skill and subskill **and** the same motif kind (missing your own mate ≠ allowing the opponent's). Unexplained errors are never matched, and rejected findings never count.
  - Links are listed oldest first and marked earlier or later. The viewer flags repeated moves in the move list, and links open the exact move (`?ply=`).
- **Analysis status:**
  - `GET /games/{id}/analysis-status` returns not_requested, queued (with jobs ahead), running, deepening, analyzed or failed.
  - The games list shows each game's status, updates live, and has **Analyze all**.
  - The viewer never polls for a 404.
- **Game page redesign:**
  - The original uploaded game (parsed from the stored PGN) is on the left: board with last-move highlight, players with a "you" tag, navigation buttons and a full two-column move list. It is viewable even before analysis.
  - The analysis of the current move is on the right, in plain language. The verdict uses the classifier's thresholds (Best / Good / Inaccuracy / Mistake / Blunder / Missed a forced mate). The panel describes the position before and after, the better move (green arrow), what the move allowed (orange arrow), and same-mistake links. Opponent moves show the resulting position and your best reply.
  - Key-moment chips, a clickable winning-chances graph, and a "How to read this" legend.
  - **Keyboard:** ↓/→ next, ↑/← back, Home/End, N/P next and previous mistake, Esc stops exploring.
  - Two bugs found by the browser tests and fixed: fast key presses lost steps (stale position, fixed with a ref), and board inputs are now memoized with a shorter animation, so stepping feels snappy and drags aren't disturbed.
- **Annotations for both sides** (`annotation/`, `GET /games/{id}/annotations`):
  - Every move gets a verdict from the classifier's thresholds.
  - **Opponent moves are graded too, with no extra engine work.** Their before and after evaluations come from the analysis around the student's moves. These grades are display-only and never enter the profile.
- **Plain-language "why"** (`annotation/explain.py`), worked out on the board:
  - forced mates
  - material when the engine's line is played out, netted like a player would say it ("a knight for a pawn", "the exchange")
  - verified forks and undefended pieces in the better move or the reply
  - otherwise an honest "positional" statement with the engine's margin
- **Standard notation everywhere:** + = White better, − = Black better, #3 / #−3 for mates. The words name the student's colour ("you (Black) were winning").
- **One-screen workspace:**
  - The left column holds the key moments (one line that scrolls sideways), a vertical eval bar beside the board (oriented like the board, one decimal), the navigation row with the keyboard hint, and the graph.
  - The right column holds the live engine at the top, then this move's verdict and "why", then the move list, which fills the remaining height.
  - Both columns are sticky. The board size comes from the viewport (`--board-size` / `--chrome` in `styles.css`).
  - Stepping never scrolls the page: the move list scrolls itself to the active move.
  - `e2e/layout.spec.ts` checks the fit and the zero page scroll at 1366×768, 1536×864 and 1920×1080. Set `LAYOUT_SHOTS=<dir>` to save screenshots.
  - Fixed along the way: key presses were still dropped occasionally. A router-driven URL update is asynchronous, and live-engine re-renders in between read a stale ply. The ply now lives in component state and is mirrored to the URL with `history.replaceState`; a real navigation (`?ply=` from a link) still wins.
- Browser tests cover both: the engine finds **#1 Qxf7#**, explore mode handles a finished game, and the earlier game opens at the linked move. The e2e harness signs the admin in once per run, because the 10-per-15-minutes login throttle tripped on repeated runs.
- **Roles: students act, coaches monitor. Nobody reviews findings.**

  | Action | Student (own record) | Coach | Admin |
  |---|---|---|---|
  | Add PGNs, confirm their side, queue analysis | yes | no, read-only | yes (support) |
  | Forced re-analysis (`force=true`) | no | no | yes |
  | See mistakes game by game (`GET /students/{id}/mistakes`) | yes | yes, read-only, with acknowledgements | yes |
  | Acknowledge a mistake (`PUT`/`DELETE /games/{id}/mistakes/{ply}/acknowledgement`) | yes | no | no |
  | AI training recommendation (lesson, full LLM output) | yes, in Exercises | reads every one, with model and validation status | no |
  | Create and solve exercises | yes | no | no |
  | Confirm, reject or correct findings | no | no | yes, research labelling only |
  | Create students, aliases, logins; delete data | no | yes | yes |
  | Mistakes across students (`GET /cohort/mistakes`) | no | own students only | all |

  - **Product decision (2026-10-21):** findings are not reviewed or approved by anyone. The student sees them straight away and acknowledges them. This replaces the earlier "candidates until a coach confirms them" principle (see `AGENTS.md`). The review endpoint stays for administrators, because research evaluation still needs human gold labels; it is not part of the product UI.
  - The profile is unchanged (`profile-v1`): unreviewed findings keep their weight of 0.5. Since every finding is now unreviewed, that weight applies uniformly, so rankings are unaffected. The profile is rebuilt automatically after each analysis, and nobody rebuilds it by hand.
  - **Mistakes** (`mistakes.py`): a mistake is one of the student's moves with a current finding. The classifier stores one for every non-forced move from inaccuracy upwards, as `unclassified` when no cause is verified. Mistakes are grouped by analyzed game, newest first, paged by game. Each one has:
    - the verdict, the evaluation before and after, the better move and line, and the board-derived "why" (from `annotation/`)
    - the mistake types and earlier occurrences (from the findings)
    - its acknowledgement
    - `flagged_again`: the earlier acknowledged mistake of the same kind (same skill, subskill and motif kind), when there is one
  - **Acknowledgements** (`mistake_acknowledgements`, migration `2ab0d3d6f02f`): one row per (game, ply), keyed by move rather than by finding, so re-analysis and reclassification never lose them. Only the student's own login can acknowledge, and only their own moves. Acknowledging is audited and never changes a finding or the profile. Deleted with the student.
  - **Exercises tab (student):** the latest AI recommendation in full (objective, positions from their games, "Your turn", the recommended practice, follow-up, what is known or not), with "New recommendation". "Practise this" creates exercises for exactly the recommendation's skill and subskill (`objective` on `CoachingSessionOut`), and lists them under "For this recommendation". The template fallback is now `template-v2`, which drops the coach-review wording.
  - **Mistakes across students** (`cohort.py`): the coach's own students' current findings, grouped by skill and subskill, with the students affected, acknowledged and open counts, and the three most recent examples linked to the exact move. Unexplained errors are listed last.
  - `games.imported_by` (migration `3d1950a20ab5`, nullable) records who added each game. It's per game because identical files are stored once and can be imported for several students. Older games stay NULL rather than being guessed. The games list returns `added_by` ("student", "coach" or null), a role and never an identity.
  - `file_previously_uploaded` reflects only this student's own imports.
  - **Student UI:** My games, My mistakes, Exercises, My profile, Progress. A new student lands on My games, and a student with games lands on My mistakes. A getting-started card shows until the first game is analyzed.
  - **Coach UI:** top navigation has Students and Mistakes across students. The student list shows games, games added by the student, open mistakes (not yet acknowledged, out of the total) and whether there is a login. Per student: Games, Mistakes, Profile, Recommendations, Progress and Account, all read-only except Account.
  - Tests act as the student with `client.as_student(student_id)` and label as an admin with `client.as_admin` (`tests/conftest.py`). The e2e specs set up a coach, student and login through `e2e/helpers.ts`.

### Known limitations (MVP)

- Statistical claims need a real cohort: the spec's 10–30 students, coach-annotated gold labels, and blinded ratings. The tooling exists, the data doesn't yet.
- Exercises are single-move, there is no "avoid the blunder" type, and there are no unseen-position puzzles. A themed puzzle bank (for example the CC0 Lichess database) is the natural next step for pre/post measurement.
- Detectors don't yet cover pins, skewers, discovered attacks, or attacks on a pawn plus a piece.
- Rate limits are per process. There are no refresh tokens, and no admin screen for user management.
- Not yet run against a live LLM, because no credentials are configured. The validator and fallback are tested with mock providers.
