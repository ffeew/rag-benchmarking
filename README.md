# SEC Filings Agentic RAG Benchmark

Implementation of the system in [docs/system-design.md](docs/system-design.md): FastAPI + Celery backend, Postgres/pgvector retrieval store, MinIO artifact storage, OpenRouter/Mistral provider layer, and a React/Vite operator workspace.

## Repo Layout

- `backend/`: Python 3.13 FastAPI API, Celery workers, SQLAlchemy models, Alembic migrations, ingestion, retrieval, query tracing, and evaluation code.
- `frontend/`: React + Vite + TypeScript workspace for datasets, documents, jobs, query, traces, evaluations, and status.
- `docs/`: system design, ADRs, and implementation report.
- `sec_filings_pdf/`: seed corpus path expected by local ingestion.

## Run Locally

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

Open:

- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- MinIO console: `http://localhost:9001`

The default `backend/.env.example` uses `ALLOW_MOCK_PROVIDERS=true`, so the stack can smoke-test without paid provider keys. For live parsing/generation, set OpenRouter and Mistral keys/models in `backend/.env` and set `ALLOW_MOCK_PROVIDERS=false`.

## Ingest The Seed Corpus

In the frontend, enter the bearer token from `backend/.env`, then:

1. Use `Register Local Corpus` to upload/register PDFs from `LOCAL_CORPUS_PATH`.
2. Watch the automatically queued ingestion jobs in `Jobs`.
3. Ask questions in `Query`; answers include page citations, evidence chunks, and trace IDs.

Equivalent API call:

```bash
curl -X POST http://localhost:8000/v1/datasets/register-local-corpus \
  -H "Authorization: Bearer change-me-local-token" \
  -H "Content-Type: application/json" \
  -d '{"dataset_name":"sec-filings"}'
```

## Custom Dataset

Put PDFs in the same shape as the seed corpus:

```text
my_filings/
  TICKER/
    TICKER_10-K_YYYYMMDD.pdf
```

Then set `LOCAL_CORPUS_PATH` in `backend/.env` or mount the path into the API/worker containers and call the same registration endpoint.

## Reproduce Reported Metrics

The implementation report (`docs/implementation-report.md`) cites aggregate
retrieval, generation, and ablation metrics computed against the verified
eval set in `backend/eval_cases/sec_filings_v1.yaml` (63 cases across 9
categories, all grounded in PDFs under `sec_filings_pdf/`). To reproduce:

```bash
# 1) Bring up the stack and ingest the seed corpus (see "Run Locally" + "Ingest
#    The Seed Corpus" above). Note the dataset id printed by the registration
#    response (or read it from the frontend Dataset overview).

# 2) Seed the verified eval cases into that dataset (idempotent upsert):
uv run --directory backend python -m rag_benchmarking.scripts.seed_eval_cases \
  --dataset <dataset_id> \
  --file backend/eval_cases/sec_filings_v1.yaml

# 3) Run all three ablation variants and write the raw artifact to
#    artifacts/evals/<eval_run_id>.json. The runner evaluates all variants
#    in a single eval run, so one invocation produces the full comparison.
uv run --directory backend python -m rag_benchmarking.scripts.run_eval \
  --dataset <dataset_id> \
  --variants full_agentic,single_pass,llm_only \
  --output markdown

# 4) (Optional) Pretty-print the ablation table from a saved artifact:
uv run --directory backend python -m rag_benchmarking.scripts.compare_ablations \
  --artifact backend/artifacts/evals/<eval_run_id>.json \
  --include-by-category
```

The Evaluations dashboard in the frontend renders the same eval-run object,
including per-case metrics and representative failures. Expected aggregate
numbers and the discussion of ablation lift, failure modes, and limitations
live in `docs/implementation-report.md` §Results.

## Implementation Report

Method choices, evaluation methodology, results, ablation findings, failure
modes, and limitations are written up in [`docs/implementation-report.md`](docs/implementation-report.md).
ADRs for individual decisions are in [`docs/adr/`](docs/adr/).

## Demo Video

A walkthrough of registration → ingestion → query (with citations and trace
viewer) → ablation evaluation is linked in `docs/implementation-report.md`
once recorded.

## Verification

Backend:

```bash
uv run --directory backend ruff check .
uv run --directory backend mypy rag_benchmarking tests
uv run --directory backend pytest
```

Frontend:

```bash
cd frontend
pnpm lint
pnpm build
```
