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
# Official Stockfish release, pinned by version and verified by SHA-256 so every analysis
# environment uses the identical binary. Change all three args together.
# Digests: https://api.github.com/repos/official-stockfish/Stockfish/releases/tags/<tag>
ARG STOCKFISH_TAG=sf_18
ARG STOCKFISH_BUILD=stockfish-ubuntu-x86-64-avx2
ARG STOCKFISH_SHA256=536c0c2c0cf06450df0bfb5e876ef0d3119950703a8f143627f990c7b5417964
ADD --checksum=sha256:${STOCKFISH_SHA256} \
    https://github.com/official-stockfish/Stockfish/releases/download/${STOCKFISH_TAG}/${STOCKFISH_BUILD}.tar \
    /tmp/stockfish.tar
RUN tar -xf /tmp/stockfish.tar -C /tmp \
    && install -m 0755 /tmp/stockfish/${STOCKFISH_BUILD} /usr/local/bin/stockfish \
    && rm -rf /tmp/stockfish /tmp/stockfish.tar
ENV STOCKFISH_PATH=/usr/local/bin/stockfish
USER app
CMD ["python", "-m", "chesscoach.analysis.worker"]
