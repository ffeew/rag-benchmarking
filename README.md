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

### Run in Production Mode

`docker-compose.prod.yml` is an overlay on `docker-compose.yml` — it builds the SPA via the frontend image's `publisher` stage into a named volume, then FastAPI serves it directly. Pass both files (the overlay only contains the deltas):

```bash
export UID=$(id -u) GID=$(id -g)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

Everything is fronted by the API at `http://localhost:8000/` (the SPA, `/docs`, and the JSON API). Port 3000 is intentionally not exposed.

Stop with the same file pair:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
```

The prod build retags the `rag-benchmarking-frontend` image with the publisher stage. To switch back to dev hot-reload afterwards, rebuild the frontend image: `docker compose build frontend && docker compose up -d`.

## Custom Dataset

Put PDFs in the same shape as the seed corpus — the local-corpus scanner globs
`<LOCAL_CORPUS_PATH>/*/*.pdf`, so PDFs must sit one level below the corpus root
(ticker subdirectories), not directly under it:

```text
my_filings/
  TICKER/
    TICKER_10-K_YYYYMMDD.pdf
```

Then set `LOCAL_CORPUS_PATH` in `backend/.env` or mount the path into the API/worker containers and call the same registration endpoint.

### Domain-Adaptive Retrieval Config

The prompts used by the planner, HyDE, retrieval-agent, verifier, and generator are
not hard-coded to SEC filings; they read corpus-level overrides from the dataset row.
Existing SEC behavior is preserved because every override falls back to a SEC default
when the column is null. Override columns on `datasets`:

| Column | Purpose |
| --- | --- |
| `domain_label` | Short corpus identity injected as `CORPUS: …` in every agent prompt (default: "SEC filings of US public companies"). |
| `entity_label` | Human-readable name for the primary entity (default: "ticker"). |
| `valid_forms` | JSON array of allowed form types; restricts planner output and `retrieve_evidence` filters (default: `["10-K","10-Q","8-K"]`). |
| `metric_terms` | JSON array of metric keywords used by the heuristic-planner fallback (default: revenue, R&D, …). |
| `hyde_style_hint` | Optional dataset-specific style cue appended to the HyDE prompt as `STYLE_HINT: …`. |
| `citation_label_template` | `str.format` template with `{entity}`, `{filing_date}`, `{form_type}`, `{page}` placeholders for citation rendering (default: `[{entity} {filing_date} {form_type}, p. {page}]`). |

Pass any of these as optional fields on `POST /v1/datasets`, `POST /v1/datasets/register-local-corpus`, or via direct DB update. Example:

```bash
curl -sS -X POST http://localhost:8000/v1/datasets \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "compliance-memos",
    "description": "Internal compliance memos and incident reports.",
    "domain_label": "Internal compliance memos",
    "entity_label": "subject",
    "valid_forms": ["MEMO", "INCIDENT"],
    "metric_terms": ["incident", "escalation", "control"],
    "hyde_style_hint": "Compliance memo register: incident, remediation, control mapping."
  }'
```

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

## Reproduce Reported Metrics

The implementation report (`docs/implementation-report.md`) cites aggregate
retrieval, generation, and ablation metrics computed against the verified
eval set in `backend/eval_cases/sec_filings_v1.yaml` (99 cases across 9
categories, all grounded in PDFs under `sec_filings_pdf/`). To reproduce:

```bash
# Prereq: stack is up (see "Run Locally"), `curl` + `jq` installed locally
# (`brew install jq` / `apt-get install jq`), and API_BEARER_TOKEN matches backend/.env.
export API_BEARER_TOKEN=change-me-local-token

# 1) Register the local corpus, capture the dataset id, and wait for all
#    ingestion jobs (parse → chunk → embed) to reach a terminal state.
DATASET_ID=$(curl -sS -X POST http://localhost:8000/v1/datasets/register-local-corpus \
  -H "Authorization: Bearer $API_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dataset_name":"sec-filings"}' \
  | jq -r .dataset.id)
echo "DATASET_ID=$DATASET_ID"

until [ "$(
  q=$(curl -sS -H "Authorization: Bearer $API_BEARER_TOKEN" \
    "http://localhost:8000/v1/jobs?dataset_id=$DATASET_ID&job_type=ingestion&status=queued&limit=1" \
    | jq '.total')
  r=$(curl -sS -H "Authorization: Bearer $API_BEARER_TOKEN" \
    "http://localhost:8000/v1/jobs?dataset_id=$DATASET_ID&job_type=ingestion&status=running&limit=1" \
    | jq '.total')
  echo $((q + r))
)" = "0" ]; do
  sleep 10
done

# 2) Seed the verified eval cases into that dataset (idempotent upsert):
uv run --directory backend python -m rag_benchmarking.scripts.seed_eval_cases \
  --dataset "$DATASET_ID" \
  --file backend/eval_cases/sec_filings_v1.yaml

# 3) Run all three ablation variants and write the raw artifact to
#    artifacts/evals/<eval_run_id>.json. The runner evaluates all variants
#    in a single eval run, so one invocation produces the full comparison.
uv run --directory backend python -m rag_benchmarking.scripts.run_eval \
  --dataset "$DATASET_ID" \
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
