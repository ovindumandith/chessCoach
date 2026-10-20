# Project Specification — ChessMentor AI

The full source specification is in [`../project.md`](../project.md). This file condenses it into the commitments the code is built against.

## Goal

Analyze each student's PGN games with Stockfish and find recurring weaknesses backed by evidence. Keep a versioned skill profile for each student. Use an external LLM to explain verified findings and to set targeted exercises.

The first target is 10–30 students with about 50 historical games each.

## Users

- **Coach:** manages students, uploads PGNs, reviews evidence, confirms or corrects classifications, and edits learning plans.
  - *Implementation note (2026-10-21):* students upload and analyze their own games, acknowledge their mistakes, and get recommendations and exercises. Coaches only monitor, and findings are not reviewed in the product (admins can still label them for research). See `IMPLEMENTATION_PLAN.md`, Post-MVP additions.
- **Student:** reviews their own games and profile, completes lessons and exercises, and tracks progress.

## The five questions the system answers

1. What happened? (engine evidence)
2. Why might it matter? (candidate skill)
3. How strong is the evidence? (recurrence and confidence)
4. What next? (lesson or exercise)
5. Did it help? (exercise results and later games)

## In scope for the MVP

- PGN import with provenance, identity mapping, deduplication and an import report.
- Two-pass Stockfish analysis that is reproducible and handles perspective and mate scores correctly.
- A versioned skill taxonomy and transparent rule-based candidate detectors.
- A coach review workflow.
- Profiles adjusted for opportunities, with recurrence, confidence and a priority heuristic.
- LLM lessons with structured output and chess validation, plus a deterministic fallback.
- Exercises built from analyzed positions, with attempt tracking.
- A React coach dashboard and a student view.
- Role-based access, auditing and Docker Compose deployment.
- An evaluation module comparing three systems: engine-only, rule-based, and LLM with profile.

## Out of scope for the MVP

- Training an LLM or a separate model per student.
- Using an LLM in place of the engine.
- Psychological diagnoses.
- Live Chess.com or Lichess APIs.
- Multi-agent frameworks, vector databases, queues beyond a PostgreSQL job table.
- Social features, tournaments, live-game assistance, native mobile apps.

## Acceptance criteria

These come from `project.md` §19:

1. A coach creates a student and uploads a multi-game PGN.
2. Games are mapped to the correct student and color.
3. Stockfish analysis persists reproducible move-level results.
4. Perspective and mate scores are handled correctly.
5. Candidate weaknesses link to traceable evidence.
6. Profiles show opportunities, recurrence, confidence and uncertainty.
7. Coaches can review and correct classifications.
8. The LLM produces a structured personalized lesson.
9. Game references, FENs and suggested moves are validated.
10. Students complete exercises and their attempts are recorded.
11. New games update profiles incrementally.
12. Students cannot access other students' data.
13. Unit, integration and end-to-end tests pass.
14. The app runs locally from the documented instructions.
15. Research baselines can be reproduced from saved configurations.

## Assumptions made during implementation

These are decisions the spec leaves open. Each one is documented and configurable.

| # | Assumption | Rationale |
|---|---|---|
| A1 | Game identity is a SHA-256 of key headers (Event, Site, Date, Round, White, Black, Result) plus the UCI move list. | The same game imported from two files is detected as a duplicate. |
| A2 | Student identity comes from a set of **aliases** per student, compared case-insensitively. A game where neither side matches is `unmatched`. A game where both sides match is `ambiguous`. Neither kind is assigned automatically. | The spec says not to assume a PGN name uniquely identifies a student. |
| A3 | Unmapped games are still stored, with `mapping_status` set, so a coach can confirm them later without re-uploading. | Nothing is silently discarded. |
| A4 | Games with python-chess parse errors or illegal moves are **rejected** and listed in the import report. They are not stored as games. | Keeps the analysis pipeline clean while keeping the reason visible. |
| A5 | SQLite is allowed for local development and fast tests. PostgreSQL is required for Docker and production. | Docker is not available on every developer machine. |
| A6 | Until Phase 8 adds real authentication, a development-only stub user (a coach) is used. It refuses to run when `APP_ENV=production`. | Access checks through `student_access` are enforced in services from day one. |
