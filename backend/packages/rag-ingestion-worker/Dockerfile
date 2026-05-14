# Image for the ingestion worker (Celery consumer of the ingestion queue).
# Owns PDF parsing and chunking deps (pypdf, chonkie, Mistral OCR client).
# RAGAS / rag-retrieval live in `rag-evaluation-worker` and never enter this image.
#
# Build context is the backend root (./backend) so uv sees the whole workspace.
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
COPY packages/rag-evaluation-worker/pyproject.toml packages/rag-evaluation-worker/

# Source for everything in this package's closure (rag-common only — no
# rag-retrieval, no rag-evaluation-worker; the API and evaluation worker
# own those).
COPY packages/rag-common packages/rag-common
COPY packages/rag-ingestion-worker packages/rag-ingestion-worker

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package rag-ingestion-worker
