# Lean image for the API + migrate + scheduler/maintenance roles.
#
# Installs only the `rag-benchmarking` workspace package and its closure
# (rag-common + rag-retrieval), so heavy ingestion/eval deps (docling, ragas,
# chonkie, pypdf, mistral OCR) — which live exclusively in `rag-ingestion-worker`
# — never land in this image.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Manifests first so dep resolution is cacheable independent of source edits.
COPY pyproject.toml uv.lock README.md ./
COPY packages/rag-common/pyproject.toml packages/rag-common/
COPY packages/rag-retrieval/pyproject.toml packages/rag-retrieval/
COPY packages/rag-ingestion-worker/pyproject.toml packages/rag-ingestion-worker/

# Source for everything in this package's closure.
COPY packages/rag-common packages/rag-common
COPY packages/rag-retrieval packages/rag-retrieval
COPY rag_benchmarking ./rag_benchmarking
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

# Install just the rag-benchmarking package + workspace deps. No dev tools, no
# rag-ingestion-worker (its heavy deps stay out of this image).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package rag-benchmarking

EXPOSE 8000
