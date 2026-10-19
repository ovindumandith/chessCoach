# Data Model

The source of truth is `src/chesscoach/db/models.py`. Schema changes go through Alembic (`migrations/`).

## Conventions

- UUID primary keys (`sqlalchemy.Uuid`), generated in Python.
- Timezone-aware UTC timestamps (`created_at`, `updated_at`).
- String-backed enums (`native_enum=False`) with CHECK constraints.
- `JSON` that becomes `JSONB` on PostgreSQL, used only for flexible metadata such as headers, configs and warnings. Never use it for fields that queries filter on.
- Raw evidence (`source_files`, `games.raw_pgn`, `analysis_runs`, `move_analyses`) is never modified when profiles are recomputed.

## Entities

| Table | Purpose | Key columns |
|---|---|---|
| `users` | Application accounts | `email` (unique), `password_hash`, `role` (coach/student/admin), `is_active` |
| `students` | Coached players | `display_name`, `rating_estimate`, `rating_source`, `skill_level`, `learning_preferences` |
| `student_aliases` | PGN names that identify a student | `student_id`, `alias`, `alias_normalized` (unique per student) |
| `student_access` | Which user can see or coach which student | `user_id`, `student_id`, `access_level` (coach/self) — unique pair |
| `source_files` | Uploaded PGN files | `original_filename`, `sha256` (unique), `storage_key`, `file_size`, `uploaded_by`, `import_status`, `warnings`, `import_report` |
| `games` | One game from a file | `source_file_id`, `game_index`, `game_hash` (unique), `white_name`, `black_name`, `student_id?`, `student_color?`, `mapping_status`, `result`, `played_at`, `time_control`, `opening_eco`, `has_clock`, `pgn_headers`, `raw_pgn` |
| `analysis_runs` | One engine pass over a game (also the job queue) | `game_id`, `engine_name/version/checksum`, `configuration`, `analysis_version`, `pass_type` (baseline/critical), `status`, `attempts`, `claimed_by`, `started_at`, `completed_at`, `error_message` |
| `move_analyses` | Analysis of one student move | `analysis_run_id`, `ply` (unique per run), `fen_before/after`, `uci_move`, `san_move`, `student_move`, `phase`, `eval_before_cp`, `eval_after_cp`, `eval_before_mate`, `eval_after_mate`, `best_move_uci`, `principal_variation`, `best_move_loss_cp`, `win_prob_loss`, `clock_before_ms`, `clock_after_ms` |
| `weakness_observations` | Candidate or confirmed skill evidence | `student_id`, `game_id`, `move_analysis_id`, `skill_code`, `subskill_code`, `evidence_type` (move_quality/motif/skill_inference), `severity`, `confidence`, `classifier_version`, `review_status`, `reviewed_by`, `reviewed_at`, `details` |
| `student_skill_profiles` | Versioned per-skill snapshot | `student_id`, `skill_code`, `profile_version`, `state`, `error_rate`, `opportunity_count`, `error_count`, `games_affected`, `confidence`, `priority_score`, `evidence_summary`, `settings` |
| `learning_plans` | Objectives for a student | `profile_version`, `objective`, `weekly_goals`, `recommended_skills`, `status` |
| `coaching_sessions` | One LLM (or fallback) lesson | `model_provider`, `model_id`, `prompt_version`, `evidence_references`, `request_metadata`, `response_json`, `validation_status`, `token_usage`, `latency_ms` |
| `exercises` | A practice position | `student_id`, `skill_code`, `source_game_id`, `source_move_analysis_id`, `start_fen`, `accepted_moves`, `solution_source`, `validation_status`, `difficulty`, `explanation` |
| `exercise_attempts` | A student's attempt | `exercise_id`, `student_id`, `submitted_move`, `is_correct`, `hints_used`, `time_taken_ms`, `completed_at` |
| `audit_events` | Sensitive actions | `actor_user_id`, `action`, `entity_type`, `entity_id`, `details`, `created_at` |

## Status enums

- `ImportStatus`: `pending`, `completed`, `completed_with_errors`, `failed`
- `MappingStatus`: `mapped`, `unmatched`, `ambiguous`, `confirmed` (a coach resolved it manually)
- `JobStatus`: `queued`, `running`, `completed`, `failed`
- `ReviewStatus`: `candidate`, `confirmed`, `rejected`, `corrected`
- `ProfileState`: `insufficient_evidence`, `emerging_pattern`, `recurring_weakness`, `no_issue_detected`

## Indexes

Indexes are on `student_id`, `game_id`, `analysis_run_id`, `skill_code` and timestamp columns. There are unique constraints on `source_files.sha256`, `games.game_hash`, `(analysis_run_id, ply)` and `(student_id, skill_code, profile_version)`.
