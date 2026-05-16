# Lean image for the API + migrate + scheduler/maintenance roles.
#
# Installs only the `rag-benchmarking` workspace package and its closure
# (rag-common + rag-retrieval), so heavy ingestion/eval deps (docling, ragas,
# chonkie, pypdf, mistral OCR) — which live exclusively in `rag-ingestion-worker`
# / `rag-evaluation-worker` — never land in this image.
#
# Two stages: `builder` pulls the toolchain + uv + workspace manifests and
# synthesises /opt/venv; `runtime` is a clean slim image with just the venv,
# the app source, curl (for HEALTHCHECK), and a non-root user.

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
# Source edits below this line don't bust this cache layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --package rag-benchmarking

# Source for everything in this package's closure.
COPY packages/rag-common packages/rag-common
COPY packages/rag-retrieval packages/rag-retrieval
COPY rag_benchmarking ./rag_benchmarking
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

# Install the workspace project itself (fast — deps already resolved).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package rag-benchmarking

# ---------- runtime ----------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# curl powers the HEALTHCHECK below. No build toolchain in this stage.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system app \
 && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder --chown=appuser:app /opt/venv /opt/venv
COPY --from=builder --chown=appuser:app /app /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
