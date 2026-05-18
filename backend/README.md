# Backend

FastAPI, Celery, SQLAlchemy, Alembic, MinIO, pgvector, and provider integration code for the SEC filings RAG benchmark. See `docs/system-design.md` and the ADRs under `docs/adr/` for the architecture; this README only covers running the backend itself.

## Layout

- `rag_benchmarking/` — FastAPI app, API routes, ingestion orchestration, worker dispatch, operator-triggered stuck-job sweep, and operational scripts.
- `packages/` — installable monorepo packages:
  - `rag-common` — shared config, schemas, DB models, providers, pricing, job state, logging.
  - `rag-ingestion-worker` — Celery worker for OCR/parse/chunk/embed.
  - `rag-retrieval` — query planning, hybrid retrieval, verification, answer generation.
  - `rag-evaluation` — evaluation runner (per-case scoring, RAGAS, ablation analysis). Imported in-process by the API; no longer a Celery worker.
- `migrations/` — Alembic schema versions.
- `tests/` — pytest suite. `conftest.py` spins up a pgvector testcontainer reused across the session.
- `eval_cases/` — curated gold YAML for the scientific-benchmark profile.
- `scripts/` — one-shot CLIs (e.g. `seed_eval_cases`).

## Run Locally

Use `docker compose up --build` from the repo root for the full stack. To work on just the backend, copy the env template and point at a local Postgres/Redis/MinIO:

```bash
cp .env.example .env
uv run --directory . uvicorn rag_benchmarking.main:app --reload
```

`.env` defaults to `ALLOW_MOCK_PROVIDERS=true`, which lets the API and workers boot without OpenRouter or Mistral keys.

## Migrations

```bash
uv run --directory . alembic upgrade head
uv run --directory . alembic revision -m "describe change" --autogenerate
```

The `migrate` service in `docker-compose.yml` runs `alembic upgrade head` on startup.

## Tests, Lint, Type Check

The test suite imports worker packages that are intentionally omitted from the root project's prod deps (to keep the API image lean). Run `uv sync --all-packages` once after a fresh checkout so every workspace member is installed into the venv.

```bash
uv sync --all-packages                          # one-time: pull in worker packages for tests
uv run --directory . pytest                     # full suite (starts pgvector testcontainer once)
uv run --directory . pytest tests/test_<name>.py -v
uv run --directory . ruff check .
uv run --directory . mypy rag_benchmarking tests
```

The testcontainer image pin (`pgvector/pgvector:pg17`) matches docker-compose so the schema, vector extension, and JSONB operators behave identically to production.

## Workers

Ingestion is the only background queue. The API publishes through `rag_common.constants.TASK_INGEST_DOCUMENT` so the producer doesn't import the consumer package; the `rag-ingestion-worker` package consumes the `ingestion` queue and runs OCR / parse / chunk / embed.

Evaluations run in-process inside the API via `rag_benchmarking.evaluation.launch_evaluation_thread`.

When a job gets stuck (broker drop, worker crash mid-task), call `POST /v1/jobs/sweep` to redispatch queued rows and reap silent runners. The logic lives in `rag_benchmarking/workers/sweeper.py:run_sweep` and is invoked inline by the route — there is no scheduled sweep. Orphan `QueryTrace` rows are cleaned up by FK cascade when their parent dataset is deleted.
