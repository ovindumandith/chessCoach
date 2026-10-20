# Operations

This guide covers running ChessMentor AI for a real pilot. Commands assume Docker Compose from the repository root.

## First start

```bash
cp .env.example .env          # then set APP_SECRET_KEY, POSTGRES_PASSWORD (see checklist)
docker compose up -d --build
docker compose exec backend python -m chesscoach.bootstrap --email you@example.org
```

Open http://localhost:8080 and sign in as the admin. Create coach accounts with `POST /api/v1/users` (admin only). Coaches create students and their logins from the UI.

## Production checklist

- [ ] `APP_ENV=production`. The backend refuses to start without a random `APP_SECRET_KEY` of 32+ characters: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- [ ] `AUTH_DEV_BYPASS=false`. It is ignored in production anyway.
- [ ] A strong `POSTGRES_PASSWORD`. Don't publish port 5432 outside the host: remove the `ports:` entry from `db`.
- [ ] Put HTTPS in front of the `frontend` service (port 8080), for example with Caddy, Traefik or nginx with Let's Encrypt. Login tokens must never travel over plain HTTP.
- [ ] `CORS_ORIGINS` lists only origins that call the API directly. The bundled frontend is same-origin and needs none.
- [ ] Keep `STOCKFISH_THREADS=1` for reproducible analysis. Scale throughput with more workers instead (`docker compose up -d --scale worker=2`).
- [ ] Run one backend process only, or move rate limits to a shared store. The rate limiter is in-memory per process.
- [ ] Get consent from students, and from guardians for minors, before importing their games (project.md §28).
- [ ] Schedule the backups below and run a restore test at least once.

## Backup

The state lives in two places: **PostgreSQL** and the **`uploads` volume** (original PGN files, stored by SHA-256).

```bash
# Database (custom format, compressed)
docker compose exec -T db pg_dump -U chesscoach -Fc chesscoach > backup-$(date +%F).dump

# Original PGN files
docker run --rm -v chesscoach_uploads:/data:ro -v "$PWD":/backup alpine:3.22 \
    tar czf /backup/uploads-$(date +%F).tgz -C /data .
```

Store backups off the host and encrypt them: they contain student data.

## Restore

```bash
docker compose up -d db
docker compose exec -T db psql -U chesscoach -c "DROP DATABASE chesscoach;" -c "CREATE DATABASE chesscoach;"
docker compose exec -T db pg_restore -U chesscoach -d chesscoach --no-owner < backup-YYYY-MM-DD.dump
docker run --rm -v chesscoach_uploads:/data -v "$PWD":/backup alpine:3.22 \
    tar xzf /backup/uploads-YYYY-MM-DD.tgz -C /data
docker compose up -d
```

**Verified** on 2026-10-20: a dump was restored into a scratch database. Students, games, analyzed moves, findings and the Alembic revision all matched the live database exactly.

**Restore drill (recommended monthly):** restore into a scratch database (`CREATE DATABASE restore_check`), compare row counts, then drop it. This leaves production untouched.

## Deleting a student's data

Deletion is irreversible. It removes the student and everything derived from their games:
- games
- analysis
- findings
- opportunities
- profiles
- lessons
- exercises and attempts

Uploaded PGN files are deleted unless another student's games still use them. The student's own login is **anonymized and deactivated**, not deleted, so the audit trail stays consistent but no longer identifies anyone. Audit events keep IDs and counts only, never names or PGN content.

From the API (the student's coach):

```bash
curl -X DELETE "https://host/api/v1/students/<id>?confirm=<exact display name>" \
     -H "Authorization: Bearer <token>"
```

From the server:

```bash
docker compose exec backend python -m chesscoach.privacy delete-student <id> --confirm "<exact display name>"
```

**Backups still hold the deleted data** until they age out. Set a retention period for backups that matches your privacy policy.

## Upgrades

```bash
git pull
docker compose up -d --build           # the migrate service runs `alembic upgrade head` first
```

- **New classifier version** (`CLASSIFIER_VERSION`): run `docker compose exec backend python -m chesscoach.classification.reclassify`. Stored engine analysis is reused, and coach reviews carry forward to the new version.
- **New analysis version** (`ANALYSIS_VERSION`): existing analyses stay valid. Games are re-analyzed only when someone requests it.
- **Never run `docker compose down -v`**: it deletes the database and uploads volumes.

## Enabling LLM coaching

```dotenv
LLM_ENABLED=true
LLM_PROVIDER=anthropic          # or openai_compatible with LLM_BASE_URL
LLM_MODEL=claude-opus-5-5
LLM_API_KEY=...
```

Every lesson is validated against stored evidence. If validation fails twice, or the provider fails, a template lesson is served instead. Each `coaching_sessions` row records provider, model, prompt version, token usage, latency and validation errors, so cost and quality can be audited.

## Health and troubleshooting

| Symptom | Check |
|---|---|
| `GET /api/v1/health` returns 503 | The database is unreachable: `docker compose logs db` |
| Analysis jobs stay `queued` | The worker isn't running or can't find Stockfish: `docker compose logs worker` |
| Job `failed` | `GET /api/v1/analysis-jobs/<id>`. `error_message` holds the cause, and failed jobs can be re-queued with `{"force": true}`. |
| Lessons always come from the template | `LLM_ENABLED`, credentials, and `validation_errors` on the session |
| 429 responses | Rate limits (`RATE_LIMIT_*` settings). The body includes `retry_after_seconds`. |
| Logged out after an hour | `ACCESS_TOKEN_MINUTES`. There are no refresh tokens yet. |

## Research workflow

See `docs/RESEARCH_PLAN.md`. Every run writes a reproducible record (code revision, component versions, non-secret settings, seed, dataset IDs) to `data/experiments/`.

```bash
# 1. Blind annotation sheet (flagged and unflagged moves, no classifier labels shown)
python -m chesscoach.evaluation annotation-template config/experiments/pilot_v1.yaml
# 2. Coaches fill in gold_labels / is_error, then:
python -m chesscoach.evaluation benchmark config/experiments/pilot_v1.yaml --gold filled.csv
# 3. Precision of the classifier as seen through in-app coach reviews
python -m chesscoach.evaluation review-precision config/experiments/pilot_v1.yaml
# 4. Do pre-cutoff profiles predict post-cutoff errors better than a population baseline?
python -m chesscoach.evaluation predictive config/experiments/pilot_v1.yaml
# 5. Blinded A/B/C coaching comparison: package -> coaches rate -> score
python -m chesscoach.evaluation coaching-package config/experiments/pilot_v1.yaml
python -m chesscoach.evaluation coaching-score config/experiments/pilot_v1.yaml \
    --ratings ratings.csv --key KEY_do_not_share_with_raters.json
```

Inside Docker, prefix each command with `docker compose exec backend`.
