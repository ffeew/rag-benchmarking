# Image for the ingestion worker (Celery consumer of the ingestion queue).
# Owns PDF parsing and chunking deps (pypdf, chonkie, docling, Mistral OCR client).
# RAGAS / rag-retrieval live in `rag-evaluation-worker` and never enter this image.
#
# Build context is the backend root (./backend) so uv sees the whole workspace.
# Two stages: `builder` pulls the toolchain and synthesises /opt/venv;
# `runtime` is a clean slim image with just the venv, the worker source, and
# a non-root user.

# ---------- builder ----------
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Manifests first → dep resolution layer is cached independent of source edits.
# READMEs are referenced by each pyproject.toml's `[project].readme`, and
# hatchling builds editable wheels for workspace members during `uv sync` —
# so they must be present even before any source is copied.
COPY pyproject.toml uv.lock README.md ./
COPY packages/rag-common/pyproject.toml packages/rag-common/README.md packages/rag-common/
COPY packages/rag-retrieval/pyproject.toml packages/rag-retrieval/README.md packages/rag-retrieval/
COPY packages/rag-ingestion-worker/pyproject.toml packages/rag-ingestion-worker/README.md packages/rag-ingestion-worker/
COPY packages/rag-evaluation-worker/pyproject.toml packages/rag-evaluation-worker/README.md packages/rag-evaluation-worker/

# Resolve and install third-party deps without installing the project itself.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --package rag-ingestion-worker

# Source for the ingestion-worker closure: rag-common + self.
COPY packages/rag-common packages/rag-common
COPY packages/rag-ingestion-worker packages/rag-ingestion-worker

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package rag-ingestion-worker

# ---------- runtime ----------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# curl kept available for ad-hoc debugging; no HEALTHCHECK on background workers.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system app \
 && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder --chown=appuser:app /opt/venv /opt/venv
COPY --from=builder --chown=appuser:app /app /app

USER appuser
