# Backend API and analysis worker share one image; the worker adds Stockfish.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
# /data/uploads is owned by the app user so a fresh named volume inherits that ownership.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/uploads \
    && chown -R app:app /data

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

COPY alembic.ini ./
COPY migrations ./migrations
COPY config ./config
COPY prompts ./prompts

FROM base AS backend
USER app
EXPOSE 8000
CMD ["uvicorn", "chesscoach.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker
# Debian's packaged Stockfish; the worker records the exact version on every analysis run.
RUN apt-get update \
    && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*
USER app
# Placeholder until Phase 3 adds chesscoach.analysis.worker.
CMD ["python", "-c", "import time; print('analysis worker not implemented yet (Phase 3)'); time.sleep(10**9)"]
