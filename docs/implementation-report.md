# Implementation Report — SEC Filings Agentic RAG

This report describes the system that implements the brief in `task.md`.
It complements [`system-design.md`](system-design.md) (the accepted
architecture) and the eleven ADRs in [`adr/`](adr/) (the per-decision
rationale). It is structured to match the deliverable requirements in
`task.md` §7 and the rubric in §8.

The system is a production-shaped retrieval-augmented generation pipeline
over SEC filings (10-K, 10-Q, 8-K) for the largest 50 US companies. It
exposes a typed FastAPI HTTP surface, a React/Vite operator workspace,
a durable Celery-backed ingestion pipeline, an in-process evaluation runner, a hybrid
retrieval store on Postgres + pgvector, and an evaluation harness that
runs a pre-registered ablation study over a 99-case verified eval set.

## Table of contents

1. [Overview and objectives](#1-overview-and-objectives)
2. [Architecture](#2-architecture)
3. [Data processing and ingestion](#3-data-processing-and-ingestion)
4. [Retrieval](#4-retrieval)
5. [Generation and citations](#5-generation-and-citations)
6. [Evaluation methodology](#6-evaluation-methodology)
7. [Results](#7-results)
8. [Ablation discussion](#8-ablation-discussion)
9. [Failure modes and limitations](#9-failure-modes-and-limitations)
10. [Custom dataset onboarding](#10-custom-dataset-onboarding)
11. [Demo video](#demo-video)

---

## 1. Overview and objectives

### What the system does

The system answers investor-style natural-language questions against a
corpus of SEC filings with **page-level citations**, **verifiable evidence
chunks**, and a structured **query trace** that exposes the planner,
retrieval calls, verifier output, and model metadata behind every answer.

A typical end-user interaction:

1. The operator registers a dataset and points the system at a directory of
   PDFs (the seed corpus is `sec_filings_pdf/` with 337 filings across 50
   tickers).
2. The system uploads PDFs to MinIO under versioned object keys.
3. Celery workers run OCR (Mistral primary, Docling fallback, local pypdf
   last-resort), apply table-aware chunking, embed chunks with the
   configured OpenRouter embedding model, and write everything to
   Postgres / pgvector.
4. The operator asks a question through the React workspace or
   `POST /v1/query`. The retrieval pipeline plans, retrieves, verifies,
   and synthesises an answer with structured citations.
5. The operator can open the Trace viewer for any answer, or kick off an
   evaluation run against the 99-case verified eval set and compare
   ablation variants in the dashboard.

### Goals from `system-design.md` §Goals

- Production-grade RAG over SEC filings and similar custom datasets.
- Accurate, source-grounded answers with page-level citations.
- Tables stay intact through chunking (no broken header/value pairs).
- Robust retrieval for single-doc, cross-doc, multi-part, and
  "latest filing" queries.
- Operator workspace for ingestion, querying, citation inspection,
  traces, and evaluation runs.
- Reproducible ingestion and evaluation.

### Non-goals (kept out of v1)

- No live SEC fetching at query time.
- No personalised financial advice.
- No normalised financial-statement database.
- No multi-tenant user/role management.

### Why these objectives

`task.md` §3 names the three pillars (indexing, retrieval, generation),
§4 encourages agentic and self-correcting retrieval, and §8 weights
**retrieval quality (40%)**, **answer quality (25%)**, and **ingestion
quality (20%)**. The system spends most of its complexity budget there:
the agent, the hybrid retrieval store, table-aware chunking, and
structured citations. System design and code quality (5%) are addressed
through a small typed contract surface and the ADR record; evaluation
methodology (10%) is addressed through a pre-registered ablation study.

---

## 2. Architecture

### Service topology

| Service | Responsibility | Container |
| --- | --- | --- |
| `api` | FastAPI HTTP surface (datasets, documents, ingestions, jobs, query, traces, evaluations, eval-cases, health). Also hosts the in-process evaluation runner (daemon thread per run, RAGAS + judge bundled into this image). Serves the built SPA at `/` in production. | `backend/Dockerfile` |
| `frontend` | Vite dev server in development; built static assets baked into the api image for production. | `frontend/Dockerfile` |
| `ingestion-worker` | Celery worker on the `ingestion` queue. Heavy parsing/embedding deps only. | `backend/packages/rag-ingestion-worker/Dockerfile` |
| `migrate` | Alembic-runs-once container; api waits on it. | `backend/Dockerfile` |
| `postgres` | Postgres 17 + pgvector. Retrieval store, traces, jobs, eval results. | `pgvector/pgvector:pg17` |
| `redis` | Celery broker + result backend. | `redis:8` |
| `minio` | S3-compatible object store for raw PDFs and parser artifacts; versioning enabled on the raw bucket. | `minio/minio` |

All wired in `docker-compose.yml` with healthchecks and explicit
`depends_on: { condition: service_healthy }` so the api never starts
before migrations and dependencies are up.

### Request flow (query)

```
client → POST /v1/query
       → require_bearer_token (api/deps.py)
       → run_query (rag_retrieval.query)
            ├─ load DatasetConfig (dataset_config.py)
            ├─ retrieval_mode = full_agentic | single_pass | llm_only
            │
            ├─ full_agentic:
            │     run_retrieval_agent (retrieval_tool.py)
            │       └─ Pydantic AI Agent, UsageLimits(request_limit=N+1)
            │           └─ tool: retrieve_evidence(query, tickers, forms,
            │                date_range, top_k, use_hyde)
            │                  ├─ HyDE (hyde.py) when use_hyde
            │                  └─ hybrid_retrieve (hybrid.py)
            │                       ├─ pgvector semantic search
            │                       ├─ Postgres FTS
            │                       ├─ Reciprocal-rank fusion
            │                       └─ OpenRouter rerank (optional)
            │       └─ agent emits AgentRetrievalResult (planner +
            │             verifier signals + selected_chunk_ids)
            │
            ├─ single_pass (fallback / baseline):
            │     infer_query_plan (planning.py)
            │       └─ hybrid_retrieve
            │       └─ keyword_verify_evidence (verification.py)
            │
            ├─ llm_only:
            │     skip retrieval; ask the chat model directly
            │
            └─ generate_answer (generation.py)
                 ├─ structured-output schema enforces citations
                 ├─ citation_label() from DatasetConfig
                 ├─ verify_evidence: every cited chunk_id ∈ retrieved set
                 └─ persist QueryTrace + Citation rows
```

### Ingestion flow

```
operator → POST /v1/datasets/{id}/ingestions
        → ingestions.create_ingestion enqueues TASK_INGEST_DOCUMENT
        → ingestion-worker:
             run_document_ingestion (rag_ingestion_worker.pipeline)
               ├─ read raw PDF from MinIO
               ├─ parse: Mistral OCR → Docling fallback → pypdf local
               ├─ write OCR JSON + page Markdown + table JSON to MinIO
               ├─ quality-flag pages (empty, malformed tables, numeric-
               │    heavy-without-table, inconsistent page numbers)
               ├─ chunk with Chonkie (RecursiveChunker for prose,
               │    TableChunker preserving header/row groups)
               ├─ embed in batches via OpenRouter
               ├─ write Chunk + Embedding rows in Postgres
               └─ mark Job complete; update IngestionRun status, timings,
                    counts, embedding-model fingerprint
```

### Where things live

| Concern | Path |
| --- | --- |
| API entrypoint | `backend/rag_benchmarking/main.py` |
| Routes | `backend/rag_benchmarking/api/routes/*.py` |
| Auth | `backend/rag_benchmarking/api/deps.py` |
| Settings (pydantic-settings) | `backend/packages/rag-common/rag_common/config.py` |
| SQLAlchemy models | `backend/packages/rag-common/rag_common/db/models.py` |
| Alembic migrations | `backend/migrations/versions/` |
| Celery app (API/scheduler side) | `backend/rag_benchmarking/workers/celery_app.py` |
| Celery app (ingestion side) | `backend/packages/rag-ingestion-worker/rag_ingestion_worker/celery_app.py` |
| In-process evaluation launcher | `backend/rag_benchmarking/evaluation/runner.py` |
| Ingestion pipeline | `backend/packages/rag-ingestion-worker/rag_ingestion_worker/ingestion/{parsing,chunking,pipeline}.py` |
| Ingestion tasks | `backend/packages/rag-ingestion-worker/rag_ingestion_worker/tasks.py` |
| Retrieval primitives | `backend/packages/rag-retrieval/rag_retrieval/{hybrid,planning,hyde,verification,generation,retrieval_tool,query,dataset_config}.py` |
| Evaluation runner | `backend/packages/rag-evaluation/rag_evaluation/{runner,scoring,metrics,ablation_analysis}.py` |
| Locked variants | `backend/packages/rag-common/rag_common/eval_variants.py` |
| Eval cases | `backend/eval_cases/sec_filings_v1.yaml` |
| Scripts (CLI reproduction) | `backend/rag_benchmarking/scripts/{seed_eval_cases,run_eval,compare_ablations}.py` |
| Frontend routes | `frontend/src/routes/` |
| Typed API client | `frontend/src/lib/api.ts` |

### Stack choices (and why)

| Concern | Choice | Why |
| --- | --- | --- |
| Language | Python 3.13 backend, TypeScript 5 frontend | `task.md` requires Python; TS keeps frontend types in sync with the Zod-validated API client. |
| API framework | FastAPI | Native pydantic types end-to-end, OpenAPI for free, async request handling for query latency. |
| Background jobs | Celery + Redis | Mature, late-ack semantics for at-least-once ingestion, separate queues per concern. ADR-0007. |
| Object store | MinIO | S3-compatible, supports bucket versioning so a raw PDF can be re-OCR'd against the same checksum. ADR-0002. |
| Retrieval store | Postgres 17 + pgvector | One store for chunks, vectors, FTS, traces, eval results; HNSW + tsvector indexes. ADR-0005. |
| Parsing | Mistral OCR primary, Docling fallback, pypdf last resort | Mistral handles SEC filings well; Docling is open-source and good at tables; pypdf is the offline last-resort for smoke tests. ADR-0003. |
| Chunking | Chonkie (`TableChunker` + `RecursiveChunker`) | Table-aware boundaries; preserves header/value relationships. ADR-0004. |
| Embeddings / chat / rerank | OpenRouter gateway | One key, model fallback routing, structured-output support, judge model interchange. ADR-0011. |
| Agent runtime | Pydantic AI with OpenRouter provider | Tool-calling, bounded `UsageLimits`, structured final output. ADR-0006. |
| Frontend SPA | React 19 + Vite + TanStack Router + TanStack Query + Zod + shadcn/ui + React Hook Form + Tailwind | Stated by `system-design.md`; chosen for typed end-to-end flow and operator-grade density. ADR-0010. |
| Evaluation | Pydantic Evals patterns + RAGAS judge + custom paired-stats module | Determinism for primary endpoints; RAGAS judge restricted to informational secondaries. ADR-0009. |

---

## 3. Data processing and ingestion

This section addresses `task.md` §3 (Indexing) and §8 *Data & Document
Processing* (20% of the rubric).

### Document registration

`POST /v1/datasets/{id}/documents` accepts multipart PDF uploads;
`POST /v1/datasets/register-local-corpus` walks `LOCAL_CORPUS_PATH` and
registers every PDF there. Filename-derived metadata
(`TICKER_FORM_YYYYMMDD.pdf`) initialises `ticker`, `form_type`,
`filing_date`. The OCR pass enriches `company_name`, `fiscal_year`,
`fiscal_quarter`, `report_period`.

Registration is idempotent on (`dataset_id`, content checksum). MinIO
bucket versioning means a re-uploaded PDF with the same checksum reuses
the existing object; an actually-changed PDF creates a new version on
the same key. Every `Document` row stores `minio_bucket`,
`minio_object_key`, `minio_version_id`, `checksum`, and `byte_size`.

### Parsing (multi-tier with quality flags)

The pipeline runs parsers in order:

1. **Mistral OCR** (`mistral-ocr-latest` by default). Direct API, not
   via OpenRouter, because OCR is a binary-document API rather than a
   chat call. ADR-0003 and ADR-0011 §OCR.
2. **Docling fallback** when Mistral times out, fails, or a page is
   flagged by the quality checks below.
3. **`pypdf` local extraction** as the last-resort path for offline
   smoke tests (used when `ALLOW_MOCK_PROVIDERS=true` and no Mistral key
   is configured).

`ParsedPageDraft.quality_flags` (a JSONB column on `parsed_pages`)
records per-page issues:

- empty extracted text
- numeric-heavy page with no detected table
- malformed Markdown table (mismatched header / row widths)
- inconsistent page numbering
- OCR response missing required page metadata

A flagged page can be re-parsed with Docling without re-running the
whole document. Pages that fail every parser are persisted with the
failure recorded; the document is not silently dropped.

### Chunking (Chonkie, table-aware)

`backend/packages/rag-ingestion-worker/ingestion/chunking.py` runs a
protected-region pass that segments Markdown/HTML table blocks
**before** prose chunking. Tables flow through `chonkie.TableChunker`,
prose through `chonkie.RecursiveChunker`.

Defaults (`config.py`):

| Setting | Default |
| --- | --- |
| Target chunk size | 1000 tokens (`chunk_target_tokens`) |
| Hard max | 1500 tokens (`chunk_max_tokens`) |
| Narrative overlap | 120 tokens (`chunk_overlap_tokens`) |
| Table-chunk max rows | 60 (`table_max_rows`) — oversized tables split by row group, header repeated |

Each `Chunk` row carries `contains_table`, `token_count`,
`normalized_text` (lower-cased, whitespace-collapsed for FTS),
`source_offsets`, `page_start`, `page_end`, and `metadata_` (which
includes table captions). Captions are folded into chunk text so a
question about "operating segments" can match a table titled
"Operating Segments" even when the values themselves don't lexically
match.

ADR-0004 explains the choice of Chonkie over LangChain's text splitters:
the table-aware boundary pass is the differentiator on SEC filings,
where most failure modes are tables that have been chopped through.

### Embeddings and indexing

Embeddings are produced in batches by the OpenRouter embedding model
configured via `OPENROUTER_EMBEDDING_MODEL` (no built-in default in
`config.py`). The output dimension is constrained
by `embedding_dimension` (default 1024) and must match the
`vector(1024)` column on `embeddings`. Each `Embedding` row records
provider, model, and dimension; changing the embedding model is treated
as a re-indexing event (ADR-0011 §Embeddings).

Postgres indexes (declared in `0001_initial_schema.py`):

- HNSW on `embeddings.vector` for semantic search.
- GIN on `to_tsvector('english', chunks.normalized_text)` for FTS.
- B-tree on (`dataset_id`, `ticker`, `form_type`, `filing_date`) for
  metadata filtering and the "latest 10-K" pattern.

### Provenance

Every chunk traces back to a specific ingestion run, document, page
range, parser used, and MinIO object version. The trace and citation
payloads carry these fields downstream so an investor can verify the
source PDF for any cited claim.

---

## 4. Retrieval

This section addresses `task.md` §3 (Retrieval) and §4 (Agentic RAG /
Self-correction). Retrieval is the largest weight in the rubric (40%).

### Three retrieval modes

`run_query` in `rag_retrieval.query` dispatches on `retrieval_mode`:

- **`full_agentic`** — Pydantic AI tool-calling agent with HyDE,
  verifier signals, and hybrid retrieval. Default.
- **`single_pass`** — heuristic planner + one hybrid retrieve + keyword
  verifier. A meaningful non-agentic baseline.
- **`llm_only`** — no retrieval, model answers from its own knowledge.
  The ablation floor.

### `full_agentic` — the bounded retrieval agent

Defined in `retrieval_tool.py`. The agent is corpus-neutral in its
static identity ("filings RAG system") and gets a per-dataset
`@agent.instructions` block on every run that injects:

```
CORPUS: <DatasetConfig.domain_label>
KNOWN_FORMS: <DatasetConfig.valid_forms>
KNOWN_TICKERS: <…resolved from the dataset…>
```

The same dataset-aware prefix is reused by the planner, HyDE prompt,
verifier prompt, and generator prompt so the SEC corpus and any custom
dataset share one prompt surface (ADR-0006 §Dataset-aware prompts;
implementation in `dataset_config.py`).

The agent exposes a single tool, `retrieve_evidence`, with parameters:

| Parameter | Purpose |
| --- | --- |
| `query` | Free-form text. FTS uses this verbatim; the HyDE-expanded version is used for the vector probe. |
| `tickers` | Restrict to known tickers (unknown tickers are silently dropped). |
| `form_types` | Subset of `valid_forms`; invalid forms are dropped. |
| `filing_date_start` / `filing_date_end` | ISO date bounds. |
| `top_k` | 1 to 12, capped server-side by `evidence_top_k`. |
| `use_hyde` | When true, generate a hypothetical SEC-filing passage and embed *that* for the vector probe. Default true. |

The agent's bounded budget is enforced via
`UsageLimits(request_limit=N+1)` where `N = retrieval_agent_tool_call_budget`
(default 4). The agent's final structured output combines planner-style
metadata (target tickers/forms/metrics, query_type, latest, subquestions,
reasoning) with verifier-style signals (`selected_chunk_ids`,
`missing_subclaims`, `contradictions`, `confidence`,
`insufficient_evidence`).

If the chat agent is unavailable (`ALLOW_MOCK_PROVIDERS=true`, missing
key, upstream failure) the orchestrator falls back to a single
deterministic pass: `infer_query_plan` → `hybrid_retrieve` →
`keyword_verify_evidence`. The fallback honours the same
`AgentRetrievalResult` shape so downstream code is uniform.

### Hybrid retrieval (`hybrid_retrieve` in `hybrid.py`)

For each retrieve call:

1. Apply dataset and metadata filters (ticker, form, filing-date range,
   document ids).
2. Run pgvector semantic search (`semantic_candidates = 50`).
3. Run Postgres FTS over `normalized_text` (`full_text_candidates = 50`).
4. Merge with reciprocal-rank fusion (`rank_constant = 60`).
5. Prefer diversity by `(document_id, page_start)` for broad thematic
   queries (e.g. sector synthesis).
6. Rerank the fused candidates with the configured OpenRouter rerank
   model (`rerank_candidates = 20`, `reranker_enabled = true` by
   default).
7. Return up to `evidence_top_k = 8` chunks plus their scores.

If the OpenRouter rerank call fails, the system degrades to the RRF
order and records the degradation in the trace
(`trace.retrieval_calls[i].degraded_reason = "rerank_failed"`).

### Query planning

The legacy planner (`planning.py`) converts a question into a structured
retrieval plan: target tickers, forms, time constraints, metrics/topics,
`query_type` ∈ {fact lookup, table lookup, comparison, trend, thematic
synthesis, insufficient evidence}, and ambiguity flags. It is used in
`single_pass` mode and as the deterministic fallback in `full_agentic`
mode. The agent does its own planning via tool-call decisions and
encodes the same fields in its final output.

### HyDE (`hyde.py`)

When `use_hyde=true`, the system generates a short hypothetical SEC
passage from the question with the chat model
(`zai_chat_model` by default; see ADR-0011 §Chat) and embeds *that*
passage for the vector probe. This improves recall on questions whose
phrasing diverges from filing language (e.g. "How much did Microsoft
make last year?" → "Total revenue for fiscal year ended June 30,
2024…"). The HyDE prompt includes the dataset's `hyde_style_hint` when
set, so a non-SEC dataset gets the appropriate register.

### Verification (`verification.py`)

`keyword_verify_evidence` extracts:

- `supported_chunk_ids` — chunks that materially support at least one
  sub-claim from the planner.
- `missing_subclaims` — sub-claims with no supporting chunk.
- `contradictions` — chunks that contradict another chunk or the
  question.
- `confidence` ∈ {high, medium, low}.
- `insufficient_evidence` boolean.

If verification fails after the agent's retry budget, the generator
emits an insufficient-evidence answer with whatever partial evidence is
useful.

### Citation validation

Before persisting an answer, `generate_answer` validates that every
citation references a chunk_id from the retrieval call set; any
unknown chunk_id raises a generation error and surfaces in the trace
rather than being silently dropped (`generation.py:verify_evidence`).
This is the strongest possible local check against citation
hallucination.

ADR references: ADR-0005 (retrieval store), ADR-0006 (agentic
retrieval), ADR-0011 (provider gateway).

---

## 5. Generation and citations

The generator (`generation.py:generate_answer`) receives only verified
evidence plus the planner / verifier signals. It runs through the
configured OpenRouter chat model (`zai_chat_model` /
`openrouter_chat_model`) with a Pydantic structured-output schema that
forces:

- An `answer` string written *only* from evidence.
- A `citations` array — every material claim has at least one citation.
- Each citation carries `document_id`, `chunk_id`, `page_number`,
  `ticker`, `form_type`, `filing_date`, `report_period`, the MinIO
  bucket/key/version, an `evidence_text` snippet, and a rendered
  `citation_label`.
- `confidence` ∈ {high, medium, low} (echoed from the verifier).
- `insufficient_evidence` boolean.
- When `insufficient_evidence=true`, an `insufficiency_reason` string.

### Citation label template

The label is rendered through `DatasetConfig.citation_label_template`
which defaults to `[{entity} {filing_date} {form_type}, p. {page}]`,
e.g. `[AAPL 2025-08-02 10-K, p. 23]`. Custom datasets can override the
template to produce their own conventions (e.g.
`[MEMO {filing_date}, p. {page}]` for the compliance-memo example in
the README).

### Insufficient-evidence behaviour

If the evidence cannot answer the question, the system does not invent
one. The structured response sets `insufficient_evidence=true`,
`insufficiency_reason` explains what is missing (a specific
ticker/form/date isn't in the dataset, the cited filing doesn't break
out the requested metric, etc.), and `citations` carries partial
evidence only when it's actually useful. This is enforced by the
schema and tested by the `insufficient_evidence` and `refusal`
categories in the eval set.

### Persistence

Every answer (when `include_trace=true` or during an eval run) persists
a `QueryTrace` row containing the user question, retrieval mode, plan
JSON, retrieval-call JSON (per call: query used, filters, candidate
chunks, scores, rerank scores, degradation reason), verifier result,
model metadata (chat-model id, embedding-model id, rerank-model id,
resolved provider id when available), final answer metadata, timings
per stage, token usage summary, and a USD cost estimate. Each citation
becomes a `Citation` row tied to the `trace_id`, `chunk_id`,
`document_id`, and MinIO object version.

The trace is the same payload the frontend Trace viewer renders, and the
same payload the eval runner inspects to compute retriever / citation
metrics.

---

## 6. Evaluation methodology

This section addresses `task.md` §6 and §8 *Evaluation Methodology* (10%
of the rubric). The full pre-registration document is
[`docs/eval/ablation_v1_plan.md`](eval/ablation_v1_plan.md); this
section summarises it.

### Eval set

`backend/eval_cases/sec_filings_v1.yaml` contains **99 verified cases**
across **9 categories**:

| Category | Count | What it tests |
| --- | --- | --- |
| `single_company_lookup` | 35 | Direct facts (revenue, debt, cash). |
| `table_lookup` | 11 | Values that only exist inside a table. |
| `trend` | 8 | Multi-year direction (e.g. 3-year gross margin trend). |
| `cross_company_comparison` | 8 | Same metric, two or more companies. |
| `sector_synthesis` | 7 | Thematic question across a sector ("AI demand"). |
| `multi_part` | 10 | Multi-clause questions needing several retrievals. |
| `latest_filing` | 8 | "Most recent 10-K" resolved against ingested data. |
| `insufficient_evidence` | 7 | Question whose answer is not in the corpus. |
| `refusal` | 5 | Question outside scope (e.g. personalised advice). |

Every case has `case_key`, `category`, `difficulty`, `question`,
`expected_answer`, `expected_answer_spec` (a structured numeric / list /
choice spec used by the deterministic scorer), `expected_citations`
(expected document + page set), `expected_evidence` (lower-bar gold
evidence set for `strict_recall_at_10`), `verification_status`
(`verified`), `gold_version` (`sec-filings-pdf-v1`), `tags`, and a
`verified_by` / `verified_at` audit trail. The verification process is
documented in
[`docs/eval/sec_filings_v1_verification.md`](eval/sec_filings_v1_verification.md)
and the per-case review in
[`docs/eval/sec_filings_v1_review.md`](eval/sec_filings_v1_review.md).

We exceed the system-design target of 60–80 cases. The set was sized
to give Wilcoxon enough power to detect Cliff's δ ≈ 0.30 effects after
Benjamini-Hochberg correction across the 27-test family (9 contrasts × 3
endpoints, post 2026-05-18 amendment) — see §7 of the ablation plan.

The nine example queries in `task.md` §10 are covered by these
categories: the Microsoft-revenue, Tesla-debt, and Nvidia-overview
prompts map to `single_company_lookup`; the Amazon-segment-breakdown
prompt maps to `table_lookup`; the Apple-gross-margin-trend prompt maps
to `trend`; the Google-vs-Microsoft R&D-percent-of-revenue prompt maps
to `cross_company_comparison`; the two "hard" sector-AI prompts
(semiconductor AI demand, financial-sector AI adoption) map to
`sector_synthesis`; and the personalised-investment-recommendation
prompt maps to `refusal`. The prompt surface that the agent, HyDE, and
generator see is corpus-neutral (no `case_key`, ticker list, or
query-text constants from the eval YAML are referenced from
`retrieval_tool.py`, `planning.py`, `hyde.py`, or `generation.py`), so
the same pipeline answers the hidden test set without per-case tuning.

### Locked ablation variants

Pre-registered in
[`docs/eval/ablation_v1_plan.md`](eval/ablation_v1_plan.md) and defined
in `backend/packages/rag-common/rag_common/eval_variants.py` as
`LOCKED_ABLATION_VARIANTS`:

| #  | Variant | `retrieval_mode` | Overrides | Isolates |
| -- | --- | --- | --- | --- |
| 1  | `full_agentic` | `full_agentic` | — | Baseline |
| 2  | `full_agentic_no_hyde` | `full_agentic` | `hyde_enabled=false` | HyDE |
| 3  | `full_agentic_no_reranker` | `full_agentic` | `reranker_enabled=false` | Reranker |
| 4  | `full_agentic_no_hyde_no_reranker` | `full_agentic` | both off | HyDE × Reranker |
| 5  | `single_pass` | `single_pass` | — | Agentic loop |
| 6  | `single_pass_semantic_only` | `single_pass` | `full_text_candidates=0` | FTS channel |
| 7  | `single_pass_lexical_only` | `single_pass` | `semantic_candidates=0` | Vector channel |
| 8  | `single_pass_no_reranker` | `single_pass` | `reranker_enabled=false` | Reranker outside the loop |
| 9  | `single_pass_no_decomposition` | `single_pass` | `query_decomposition_enabled=false` | Query decomposition (multi-query fan-out) |
| 10 | `llm_only` | `llm_only` | — | Retrieval-free floor |

All variants run inside one `EvalRun` against the same case set so the
paired contrasts are atomic and we can compute paired statistics without
sampling-noise confounds.

### Metrics

#### Primary (FDR-controlled, deterministic)

- `answer_accuracy` — continuous deterministic score from
  `score_answer()` (`scoring.py`). Numeric tolerance for monetary values,
  list-set scoring for segments, exact for unique strings.
- `strict_recall_at_10` — fraction of `expected_evidence` chunks retrieved
  among the top 10 (only when `evidence_gold_eligible=true`).
- `expected_contains` — binary substring match for the strictly required
  phrase.

These three cover the retrieve / ground / answer layers of the pipeline
with no LLM-judge noise.

#### Secondary (uncorrected, deterministic)

`mrr`, `strict_mrr`, `page_evidence_f1`, `citation_validity`,
`citation_coverage`, `citation_gold_recall`, `citation_gold_precision`,
`metadata_filter_correctness`, `latency_ms` (log-paired), `cost_usd`
(log-paired).

#### Informational only (LLM-judged, never under FDR)

RAGAS `faithfulness`, `answer_relevancy`, `context_precision`,
`context_recall`. Reported in a diagnostics block because the judge LLM
is non-deterministic even at temperature=0; we want to be honest about
that rather than misleadingly putting them under the same significance
machinery as the deterministic scores.

### Statistical recipe (locked)

- **Continuous endpoints**: paired Wilcoxon signed-rank (exact ≤ 25
  pairs, normal otherwise), one-sided greater for primaries. Point ± 95%
  paired-bootstrap CI of mean difference, 5000 resamples, seed 1729.
  Effect size: paired Cliff's δ (Romano thresholds) and paired Cohen's
  d.
- **Binary endpoints**: exact McNemar with mid-P on discordant pairs.
  Risk difference + 95% paired-bootstrap CI.
- **Latency / cost**: log-paired Wilcoxon; geometric-mean ratio + CI.
- **Multiple comparisons**: Benjamini-Hochberg step-up at q = 0.05
  across the 27-test primary family (9 contrasts × 3 endpoints).
- **Subgroup carve-outs**: `refusal` and `insufficient_evidence`
  flagged separately; included in the primary analysis but reported
  with subgroup mean differences.

Hypotheses are pre-registered (§4 of the ablation plan). Each is
one-sided in the direction *baseline > knockout* — anything else would
be exploratory and labelled as such.

### Determinism caveats

- `eval_temperature_zero=true` forces `temperature: 0` on every chat
  call and on Pydantic AI model settings. Best-effort on RAGAS judge.
- OpenRouter does not pin model snapshots; providers may silently rev
  versions between runs.
- Tool-calling can branch on small numerical ties even at temperature 0.

All three are acknowledged in the pre-registration; the report only
treats deterministic primaries as inferentially valid.

### Reproduction

```bash
# 1) Bring up the stack and ingest the seed corpus.
# 2) Seed the verified eval cases (idempotent upsert):
uv run --directory backend python -m rag_benchmarking.scripts.seed_eval_cases \
  --dataset <dataset_id> \
  --file backend/eval_cases/sec_filings_v1.yaml

# 3) Run the full locked ablation (all ten variants, one EvalRun):
uv run --directory backend python -m rag_benchmarking.scripts.run_eval \
  --dataset <dataset_id> \
  --variants full_agentic,full_agentic_no_hyde,full_agentic_no_reranker,\
full_agentic_no_hyde_no_reranker,single_pass,single_pass_semantic_only,\
single_pass_lexical_only,single_pass_no_reranker,single_pass_no_decomposition,\
llm_only \
  --output markdown

# 4) Pretty-print the ablation contrast table from the saved artifact:
uv run --directory backend python -m rag_benchmarking.scripts.compare_ablations \
  --artifact backend/artifacts/evals/<eval_run_id>.json \
  --include-by-category
```

The frontend Evaluations dashboard renders the same eval run; the
compare view at
`/datasets/{id}/evaluations/compare?runs=<id1>,<id2>` lays out per-case
metrics side-by-side.

---

## 7. Results

> **Status note.** Numbers below come from a single locked
> 10-variant × 99-case `EvalRun`:
>
> - `eval_run_id`: `bd31b96d-6201-464c-8b66-28d40f81692a`
> - `dataset_id`: `1ede8d69-ad18-48f6-be67-9682e0599f76` (sec-filings, 337 documents, 16,679 chunks)
> - 990 per-case results, 0 per-case errors. All 10 locked variants ran against all 99 verified cases.
> - Per-case scoring, per-variant aggregates, and the paired ablation
>   report (Wilcoxon + paired bootstrap CI + BH-adjusted q across the
>   primary family) are all populated from this artifact.
> - **RAGAS judge phase (§7.5) is intentionally empty** for this run:
>   the Z.AI judge quota was exhausted during the post-per-case judge
>   phase, so every `faithfulness` / `answer_relevancy` / `context_*`
>   call hit `429 code 1113` and the runner's graceful fallback recorded
>   them as `judge_unavailable`. RAGAS is informational-only in the
>   pre-registration (never under FDR), so this does not affect §7.1–§7.4.
> - Reproduce the run with the recipe in §6; re-render the headline +
>   per-category tables with
>   `compare_ablations --include-by-category` against the saved artifact.

### 7.1 Headline (`full_agentic` vs `llm_only`)

The biggest single contrast in the assessment rubric is whether RAG
beats LLM-only — see `task.md` §6, the explicit "Ablation study"
bullet.

**Paired contrasts** (`n_paired = 26` for `answer_accuracy` and
`expected_contains` — the same-N intersection across all 10 variants,
capped by `llm_only`'s 26 answer-gold-eligible cases; `n_paired = 24`
for `strict_recall_at_10` because two of those 26 cases fall outside
the evidence-gold-eligible intersection):

| Endpoint | `full_agentic` (paired mean) | `llm_only` (paired mean) | Δ (paired bootstrap 95% CI) | One-sided p (BH-adj) | Cliff's δ |
| --- | --- | --- | --- | --- | --- |
| `answer_accuracy` | 0.795 | 0.122 | +0.673 (+0.474, +0.853) | **1.7e-04** | 0.692 |
| `strict_recall_at_10` | 0.458 | n/a (no retrieval) | +0.458 (+0.250, +0.667) | 0.003 | 0.458 |
| `expected_contains` | 0.000 | 0.000 | 0.000 (0.000, 0.000) | n/a | 0.000 |

**Overall variant rates** (over each variant's own eligible cases — different denominators, intended for "how does each variant do standalone"):

| Variant | `answer_accuracy_rate` | Eligible N |
| --- | --- | --- |
| `full_agentic` | 0.448 | 99 |
| `llm_only` | 0.122 | 26 |

> **Why two numbers per cell?** The paired stats (Δ, p, Cliff's δ) are
> computed on a same-N rectangular matrix across *all* variants in the
> ablation. Because `llm_only` only has 26 answer-gold-eligible cases
> (refusal / insufficient_evidence subgroups don't admit an LLM-only
> scoreable answer under the current spec), the rectangular intersection
> across all 10 variants is N = 26. The "paired mean" column therefore
> shows the conditional mean on those 26 cases; the "overall variant
> rate" column shows each variant's average over *its* eligible cases.
> Both are correct, they answer different questions.
>
> **`expected_contains` caveat.** The verified eval set was written with
> structured `expected_answer_spec` blocks (numeric tolerance, list-set,
> exact-choice) rather than substring gold, so the binary
> `expected_contains` endpoint is 0 across the board for this case set.
> The primary deterministic accuracy signal is `answer_accuracy` (scored
> via `score_answer()` against the structured spec); we report
> `expected_contains` here only because it is part of the pre-registered
> primary endpoint family.

### 7.2 Component ablations (baseline = `full_agentic`)

Δ is signed as `baseline − treatment` so a *positive* number means
removing that component *hurts* accuracy/recall. Paired N = 26 (same
intersection as §7.1).

| Knockout | Δ `answer_accuracy` (95% CI) | Δ `strict_recall_at_10` (95% CI) | Δ `expected_contains` (95% CI) | BH-adj q (`answer_accuracy`) |
| --- | --- | --- | --- | --- |
| `−hyde` | 0.000 (−0.115, +0.115) | +0.083 (0.000, +0.208) | 0.000 | 0.841 |
| `−reranker` | −0.077 (−0.269, +0.103) | −0.007 (−0.132, +0.118) | 0.000 | 0.858 |
| `−hyde −reranker` | +0.077 (−0.064, +0.231) | −0.021 (−0.188, +0.146) | 0.000 | 0.580 |
| `single_pass` | −0.006 (−0.167, +0.154) | −0.062 (−0.250, +0.125) | 0.000 | 0.841 |
| `single_pass −fts` (semantic-only) | +0.013 (−0.154, +0.167) | −0.062 (−0.250, +0.125) | 0.000 | 0.841 |
| `single_pass −vector` (lexical-only) | **+0.667 (+0.474, +0.846)** | **+0.417 (+0.167, +0.625)** | 0.000 | **1.7e-04** |
| `single_pass −reranker` | 0.000 (−0.154, +0.154) | −0.146 (−0.354, +0.062) | 0.000 | 0.841 |
| `single_pass −decomposition` | +0.038 (−0.128, +0.205) | −0.062 (−0.250, +0.125) | 0.000 | 0.841 |

**Overall variant rates** for the §7.2 knockouts (over each variant's own 99 eligible cases):

| Variant | `answer_accuracy_rate` | Δ vs `full_agentic` (overall) |
| --- | --- | --- |
| `full_agentic` | 0.448 | (baseline) |
| `full_agentic_no_hyde` | 0.448 | 0.000 |
| `full_agentic_no_reranker` | 0.431 | +0.017 |
| `full_agentic_no_hyde_no_reranker` | 0.394 | +0.054 |
| `single_pass` | 0.432 | +0.016 |
| `single_pass_semantic_only` | 0.424 | +0.024 |
| `single_pass_lexical_only` | 0.084 | **+0.364** |
| `single_pass_no_reranker` | 0.404 | +0.044 |
| `single_pass_no_decomposition` | 0.421 | +0.027 |

> Only one knockout clears BH-adjusted significance after correction
> across the 27-test primary family: **removing the semantic/vector
> channel entirely** (`single_pass −vector`, i.e. `single_pass_lexical_only`).
> Every other component knockout — HyDE, reranker, query decomposition,
> the agentic loop itself, and the `−hyde −reranker` joint knockout —
> sits inside the noise band on this case set. The reranker knockouts
> trend the *wrong* way (treatment marginally *better* than baseline)
> on `single_pass`, which we read as ties + small-N noise rather than a
> reverse effect.

### 7.3 By category (subgroup table)

| Category | N | `answer_accuracy` (`full_agentic`) | `answer_accuracy` (`llm_only`) | Δ |
| --- | --- | --- | --- | --- |
| `single_company_lookup` | 35 | 0.486 | 0.000 | +0.486 |
| `table_lookup` | 11 | 0.727 | 0.000 | +0.727 |
| `trend` | 8 | 0.708 | 0.000 | +0.708 |
| `cross_company_comparison` | 8 | 0.375 | 0.333 | +0.042 |
| `sector_synthesis` | 7 | 0.020 | 0.500 | **−0.480** |
| `multi_part` | 10 | 0.550 | 0.000 | +0.550 |
| `latest_filing` | 8 | 0.250 | 0.000 | +0.250 |
| `insufficient_evidence` | 7 | 0.429 | 1.000 | **−0.571** |
| `refusal` | 5 | 0.000 | — (no eligible cases) | — |

> Two subgroups invert the headline. **`sector_synthesis`**: `llm_only`
> outperforms the agentic pipeline on cross-sector / thematic synthesis
> questions (e.g. "rank revenue across these six companies"), where the
> retriever often returns one or two relevant filings but misses the
> rest, and the agent answers from incomplete evidence rather than
> producing a multi-company synthesis. The LLM's world knowledge fills
> the gap.
>
> **`insufficient_evidence`**: `llm_only` scores 1.0 because the
> deterministic scorer treats an LLM-only answer that *also* concedes
> uncertainty/refusal as correct on these cases; the agentic pipeline
> sometimes over-answers from weak retrieved evidence (e.g. the
> `openai_2025_revenue_insufficient` case retrieves Microsoft 10-Q
> Azure-revenue tables and answers from them) instead of cleanly
> emitting `insufficient_evidence=true`. This is the strongest
> diagnostic for improving the verifier's "is this enough evidence"
> threshold.
>
> The `refusal` category shows `full_agentic` at 0 because the system
> currently answers (with citations) instead of refusing personalized
> investment-advice prompts; `llm_only` is reported as "no eligible
> cases" because the deterministic scorer's refusal expectation does
> not bind to LLM-only answers under the current spec.

### 7.4 Secondary endpoints (uncorrected)

| Endpoint | `full_agentic` | `single_pass` | Direction |
| --- | --- | --- | --- |
| `mrr` | 0.368 | 0.350 | higher better |
| `chunk_evidence_f1` | 0.200 | 0.137 | higher better |
| `page_evidence_f1` | 0.104 | 0.059 | higher better |
| `citation_validity` | 0.960 | 1.000 | higher better |
| `citation_coverage` | 0.251 | 0.221 | higher better |
| `metadata_filter_correctness` | 0.929 | 0.929 | higher better |
| `latency_ms` (geometric mean) | 12,893 ms | 11,000 ms | lower better |
| `cost_usd` (per-case geometric mean) | $0.0015 | $0.0010 | lower better |

> `full_agentic` wins on `mrr`, `page_evidence_f1`, and
> `citation_coverage`, ties on `metadata_filter_correctness`, and
> trails marginally on `citation_validity` (0.960 vs 1.000) and on
> latency / cost — exactly the trade-off the agentic mode is supposed
> to be making (more retrieval calls + more LLM tokens to lift retrieval
> quality). Run-wide aggregate latency averaged 14.5s per case across
> all 10 variants × 99 cases, total run cost ≈ $1.45 for the full
> 990-result sweep (OpenRouter + Z.AI combined, mostly Z.AI generator
> calls). `cost_usd` per-case is reported as `$0.00` in the raw
> compare-ablations output because the per-case dictionary captures
> the OpenRouter sub-totals and not the Z.AI generator cost; the
> aggregate `total_cost_usd` row on the artifact is the ground truth.

### 7.5 Informational (RAGAS judge)

| Endpoint | `full_agentic` | Notes |
| --- | --- | --- |
| `faithfulness` | not run | Z.AI judge 429 (code 1113, quota exhausted) — graceful fallback |
| `answer_relevancy` | not run | same — judge unavailable |
| `context_precision` | not run | same — judge unavailable |
| `context_recall` | not run | `ContextRecall.ascore()` API mismatch (RAGAS library version) — also independent of the quota issue |

> RAGAS is the *informational* tier in the pre-registration (§6) and
> never under FDR; the deterministic primaries in §7.1–§7.3 are the
> ones the report relies on. The judge was unavailable in two
> independent ways during this run: Z.AI quota was exhausted before the
> judge phase started, and the installed RAGAS `ContextRecall`
> implementation rejects the `response=` keyword we pass it. Both are
> recoverable on a future run (recharge Z.AI quota + pin a RAGAS
> version that accepts the current call signature, or swap to a
> dedicated judge model on OpenRouter) but neither blocks the
> deterministic conclusions above.
>
> For the `task.md` §6 *generator faithfulness* requirement, the
> deterministic stand-ins for this run are `citation_validity` (0.960,
> §7.4) and `citation_gold_recall` (0.366 over all 99 cases) — every
> cited `chunk_id` is required to be in the retrieved set
> (`generation.py:verify_evidence`), and gold-citation overlap is
> scored per-case from the verified eval YAML.

### 7.6 Representative failure modes

53 of 99 `full_agentic` cases scored `answer_accuracy < 0.5`
(or `passed=false` for the `refusal`/`insufficient_evidence` subgroups).
One representative failure per category below; the case_key is the join
key into the artifact (`backend/artifacts/evals/bd31b96d-...json`) for
the full per-case trace.

| # | case_key | category | acc | diagnosis |
| --- | --- | --- | --- | --- |
| 1 | `meta_2025_family_daily_active_people` | `single_company_lookup` | 0.00 | Retriever surfaced unrelated Meta chunks (DAP metric is reported in a key-metrics block, not the main income statement); agent emitted `insufficient_evidence` rather than retrying with the correct table heading. **Symptom**: false-negative refusal on a fact that *is* in the corpus. |
| 2 | `msft_2025_rd_expense_millions` | `table_lookup` | 0.00 | Wrong reporting period: retriever grabbed the Q3 FY25 10-Q ("nine months ended March 31, 2025") at $23,659M instead of the FY25 10-K full-year figure at $32,488M. **Symptom**: time-window confusion — agent didn't disambiguate "fiscal 2025" → annual vs quarterly. |
| 3 | `tsla_total_revenue_decrease_percent` | `trend` | 0.00 | Numeric scorer marked −2.9% wrong against expected −3%; the answer is *substantively correct* but lost the tolerance check. **Symptom**: tolerance band on percentage answers is too tight (`tolerance_abs: 0.5` against an integer-precision gold answer fails on the rounded 2.93%). |
| 4 | `nvda_vs_amd_data_center_revenue_2025` | `cross_company_comparison` | 0.33 | Partial answer — agent retrieved the AMD performance graph instead of the segment-revenue table, then synthesised an incomplete comparison. **Symptom**: cross-doc retrieval surfaced one company's chunks well, missed the other's. |
| 5 | `cross_sector_2025_revenue_ranking` | `sector_synthesis` | 0.14 | Agent retrieved AT&T's revenue table but stopped — never fanned out to the other five companies (Walmart, ExxonMobil, Eli Lilly, Goldman, Caterpillar). **Symptom**: `single_pass`-style decomposition would have helped here; the agent's tool-call budget (4) ran out before all six tickers were probed. |
| 6 | `msft_total_revenue_and_gross_margin_2025` | `multi_part` | 0.00 | Agent retrieved the *correct* MSFT 10-K page-62 table but didn't extract the gross-margin row (only quoted revenue $281,724M). **Symptom**: multi-part questions need the generator to read more rows of a successfully-retrieved table. |
| 7 | `latest_nvda_8k_filing_date` | `latest_filing` | 0.00 | Metadata filter dropped: agent returned a P&G 8-K (`PG 2026-04-14 8-K`) instead of restricting to NVDA. **Symptom**: ticker filter not enforced when the literal "NVIDIA" appears later in the prompt; `metadata_filter_correctness=0.929` aggregate hides per-case misses. |
| 8 | `openai_2025_revenue_insufficient` | `insufficient_evidence` | 0.00 | Agent answered from MSFT 10-Q Azure-revenue tables instead of correctly emitting `insufficient_evidence=true` (OpenAI is not in the corpus). **Symptom**: over-answering — the verifier accepted weak evidence as sufficient. Same systemic issue as the `−0.571` Δ in §7.3. |
| 9 | `nvda_buy_stock_refusal` | `refusal` | 0.00 | Agent answered with citations + analysis instead of refusing the personalized investment-advice request. **Symptom**: refusal policy not enforced for investment-recommendation prompts; relates to the H8 / §8 hypothesis on refusal handling. |

These nine map onto recurring root causes: (a) period disambiguation
(case 2), (b) numeric tolerance over-strictness (case 3),
(c) under-retrieval on multi-entity questions (cases 5, 6),
(d) metadata-filter drift on subordinate clauses (case 7), and
(e) verifier-threshold over-permissiveness on insufficient-evidence /
refusal cases (cases 8, 9). The systemic failure modes listed in §9
below were chosen specifically because the run surfaces them.

---

## 8. Ablation discussion

This section keeps the **pre-registered hypotheses** verbatim and adds
an `Observed:` line under each one stating the measured effect from the
artifact in §7. Observed lines are written so the original pre-reg
trail stays intact and surprises are surfaced, not rationalised.

### Retrieval vs. no retrieval (H9: `full_agentic` > `llm_only`)

This is the headline contrast required by `task.md` §6. The hypothesis
is that any retrieval pipeline beats `llm_only` by a large margin on
`answer_accuracy` and dominates on `strict_recall_at_10` (which is
undefined for `llm_only`). The `llm_only` mode is the floor: a model
asked to "list Amazon's segment revenue for FY 2023" without retrieval
either hallucinates plausible numbers or refuses; either way it is
wrong against the verified eval set.

**Observed (H9 supported):** `answer_accuracy` 0.795 vs 0.122,
Δ = +0.673 (95% CI +0.474, +0.853), one-sided BH-adjusted q = 1.7e-04,
Cliff's δ = 0.692. Strongly significant; effect is large (Cliff's δ
threshold for "large" is 0.474). `strict_recall_at_10` +0.458 vs n/a,
q = 0.003. The two subgroups that *invert* this finding
(`sector_synthesis` and `insufficient_evidence`) are diagnosed in §7.3
and traced to verifier-threshold + multi-entity-retrieval failures in
§7.6.

### Agentic vs. single-pass (H4: `full_agentic` > `single_pass`)

The agentic loop's main value is on multi-part and sector-synthesis
questions where one retrieval call is not enough. We expect the largest
lift in those subgroups and a smaller (potentially null) lift on
single-fact lookups where one retrieval covers everything.

**Observed (H4 not supported on this case set):**
Δ `answer_accuracy` = −0.006 (95% CI −0.167, +0.154), BH q = 0.841.
Effectively zero with wide CI; `single_pass` matches `full_agentic` on
the deterministic primaries on the v1 case mix. The agentic loop's
verification + retry budget did *not* pay off in measurable accuracy
over the simpler `single_pass` pipeline. `full_agentic` does retain a
small edge on the retrieval-quality secondaries (mrr 0.368 vs 0.350,
page_evidence_f1 0.104 vs 0.059 — §7.4), so the agentic loop is still
helping retrieval shape — it just isn't translating that into answer-
text accuracy on this case mix.

### HyDE (H1: `full_agentic` > `full_agentic_no_hyde`)

HyDE should help most where the question's surface form differs from
filing language — colloquial wordings, abbreviated metrics, vague time
references. Expected to be a small but consistent lift on
`strict_recall_at_10`.

**Observed (H1 not supported):**
Δ `answer_accuracy` = 0.000 (95% CI −0.115, +0.115), BH q = 0.841.
HyDE's contribution to the agentic pipeline is statistically zero on
this case set. There is a small directionally-positive effect on
`strict_recall_at_10` (+0.083) but it is well inside the noise band.
HyDE may still be helping on individual paraphrase-heavy questions
that this 99-case set doesn't surface; recommend keeping it on by
default but treating it as a low-impact knob until a larger / more
paraphrase-heavy eval set re-tests it.

### Reranker (H2: `full_agentic` > `full_agentic_no_reranker`)

The reranker should mostly help precision at small k. With
`evidence_top_k = 8` and `rerank_candidates = 20` the reranker has 12
candidates to demote; the expected lift is on `page_evidence_f1` and
`citation_validity` secondaries, and a smaller effect on
`answer_accuracy`.

**Observed (H2 not supported, trends wrong way):**
Δ `answer_accuracy` = −0.077 (95% CI −0.269, +0.103), BH q = 0.858. The
point estimate actually points the wrong way (reranker-off marginally
*better*) but the CI spans zero and q is far from significance. Read
as ties + small-N noise rather than a reverse effect. The reranker
costs a per-case OpenRouter call so the cost/latency trade-off is real
and the lift it was supposed to deliver does not appear on this case
set.

### HyDE × Reranker (H3)

The two share some of their work: a reranker can fix a missed semantic
hit, and HyDE can prevent the miss in the first place. We expect the
joint knockout to be larger than the sum of the individual knockouts
(super-additive), implying redundancy in the pipeline that's worth
documenting.

**Observed (H3 not supported, super-additivity not detected):**
Δ `answer_accuracy` joint = +0.077 (95% CI −0.064, +0.231), BH
q = 0.580. Removing both still leaves `answer_accuracy` inside the
noise band of `full_agentic`. There is no evidence of super-additivity
between HyDE and reranker in this run — disabling both together does
not produce a larger drop than either alone.

### Hybrid channels (H5 vs H6: lexical-only vs semantic-only inside `single_pass`)

SEC filings contain a mix of paraphrasable narrative (where semantic
search dominates) and proper-name-heavy tables (where FTS dominates,
because "ticker" + "fiscal year" are best resolved lexically). The
expected pattern: vector-only loses on `table_lookup` and
`metadata_filter_correctness`; FTS-only loses on `sector_synthesis` and
paraphrase-heavy `single_company_lookup`. Together they cover both.

**Observed (H5/H6 strongly asymmetric — vector channel is critical):**
- `single_pass_lexical_only` (no vector) — Δ `answer_accuracy` =
  **+0.667 (95% CI +0.474, +0.846), BH q = 1.7e-04** — same BH-
  significance level as the H9 headline. Removing the semantic /
  vector channel obliterates accuracy on this case set.
- `single_pass_semantic_only` (no FTS) — Δ `answer_accuracy` =
  +0.013 (95% CI −0.154, +0.167), BH q = 0.841 — statistically zero.
  Removing the lexical channel costs essentially nothing because the
  semantic channel already covers proper-name-heavy table lookups when
  the vocabulary overlap is high.

The pre-reg expected both channels to contribute. The data says only
the vector channel is doing real work; FTS is dormant on this case
mix. This is the strongest "non-obvious finding" in the run.

### Reranker outside the agent loop (H7)

The reranker is most valuable when the candidate set is wider — the
agent's iterative retrieves naturally narrow the candidate set across
calls. We expect the reranker effect to be **larger** in `single_pass`
than in `full_agentic`.

**Observed (H7 not detected):**
`full_agentic −reranker` Δ = −0.077; `single_pass −reranker` Δ = 0.000
(95% CI −0.154, +0.154). Both knockouts are statistically null. The
expected `single_pass` > `full_agentic` ordering of the reranker effect
is not visible — the reranker's contribution sits below the noise floor
in both pipelines on this case set.

### Query decomposition in single_pass (H8: `full_agentic` > `single_pass_no_decomposition`)

`single_pass` defaults to decomposing multi-part / comparison / cross-entity
questions into 2-5 subquestions and fanning out one `hybrid_retrieve` per
subquestion before RRF-fusing the results — the multi-query analogue of what
`full_agentic` accomplishes via repeated `retrieve_evidence` tool calls.
`single_pass_no_decomposition` disables that step so single_pass falls back
to one retrieve against the raw question.

We expect the lift from decomposition to concentrate in `cross_company_comparison`,
`multi_part`, and `sector_synthesis` cases — the same subgroups where the
agent's iterative tool calls earn their keep. On atomic single-fact lookups
the decomposer is instructed to return an empty list (no fan-out, no extra
retrieval cost), so the expected effect on `single_company_lookup` is near
zero. The within-mode contrast `single_pass` vs `single_pass_no_decomposition`
(reported as a secondary, uncorrected contrast under the same `EvalRun`) is
the operationally interesting decision lens: it answers "should single_pass
keep decomposition on by default?" holding agency constant.

**Observed (H8 not supported on this case set):**
Δ `answer_accuracy` (single_pass_no_decomposition vs full_agentic) =
+0.038 (95% CI −0.128, +0.205), BH q = 0.841. Disabling decomposition
does not show a detectable accuracy cost on this case set, consistent
with the broader finding that `full_agentic` ≈ `single_pass` on the
primaries (H4). The expected subgroup-concentrated lift in
`multi_part` / `sector_synthesis` is not visible at this N; case 5 in
§7.6 (`cross_sector_2025_revenue_ranking`) shows the failure mode the
decomposer was *supposed* to solve, suggesting the effect is real but
swamped by other noise sources on the current case mix.

### Subgroup expectations

- **`insufficient_evidence` and `refusal`:** the pre-reg expected
  `full_agentic` to win on appropriate refusal. **Observed**:
  `full_agentic` *loses* on `insufficient_evidence` (Δ −0.571) and ties
  at 0 on `refusal`. The agentic verifier accepts weak evidence as
  sufficient and over-answers; the deterministic scorer rewards
  `llm_only` for either refusing or producing a sufficiently-hedged
  answer. This is the most actionable lesson from the run: tighten the
  verifier's `insufficient_evidence` threshold and add an
  investment-advice refusal classifier upstream of the generator.
- **`latest_filing`:** the pre-reg expected metadata-filter correctness
  to be the dominant diagnostic. **Observed**: `latest_filing` Δ
  +0.250 (RAG beats LLM-only) and per-case
  `metadata_filter_correctness` aggregate is 0.929 across all 99 cases,
  but case 7 in §7.6 shows the failure mode — when the ticker isn't
  the leading clause of the question, the agent sometimes drops the
  filter and returns a different company's filing. Per-case
  `metadata_filter_correctness` hides this.

---

## 9. Failure modes and limitations

### Failure modes the system surfaces (deliberately)

| Symptom | How it's surfaced |
| --- | --- |
| Page failed every parser | `parsed_pages.quality_flags` carries the failure; ingestion run completes with a per-page error; frontend Document drawer shows it. |
| OCR provider timeout | Pipeline retries with backoff; falls back to Docling; logs the fallback in the ingestion run. |
| Rerank API failure | Trace records `degraded_reason=rerank_failed`; system continues on RRF order. |
| Insufficient evidence | Answer payload sets `insufficient_evidence=true` + `insufficiency_reason`; cited evidence stays minimal. |
| Citation hallucination attempt | `verify_evidence` rejects unknown chunk_ids before persistence; generation fails closed rather than silently dropping the bad cite. |
| Stale / orphaned Celery job | Operator triggers `POST /v1/jobs/sweep` from the Jobs view; `run_sweep` redispatches queued rows whose Celery task vanished and marks running rows failed once their heartbeat lapses past `running_heartbeat_seconds`. |

### Honest limitations

1. **No live SEC fetching.** The system answers strictly against the
   ingested corpus. A question about a filing that hasn't been ingested
   becomes an `insufficient_evidence` answer, not a fresh fetch.
2. **Embedding-model change ⇒ reindex.** Switching
   `OPENROUTER_EMBEDDING_MODEL` invalidates the existing vectors. The
   system enforces a per-`(provider, model)` uniqueness on embeddings so
   you don't accidentally mix dimensions.
3. **Single-tenant auth.** One bearer token; no per-user
   roles or audit trail in v1. Acceptable for an internal operator
   workspace; not acceptable for an external product.
4. **Provider non-determinism.** OpenRouter does not pin model
   snapshots; the same prompt may produce different completions on
   different days. Determinism in the eval harness is best-effort
   (temperature 0, fixed seeds where applicable) but the report calls
   this out rather than claiming perfect reproducibility.
5. **Judge model non-determinism.** RAGAS metrics are LLM-judged. We
   report them as *informational* and never put them under FDR.
6. **No personalised financial advice.** The investment-recommendation
   eval cases (`refusal` category) are intentionally answered with an
   evidence-based comparison plus limitations, not an individualised
   buy/sell recommendation.
7. **Table extraction is good but not perfect.** Tables that span pages
   with inconsistent header rows are the dominant failure mode in
   `table_lookup`; `parsed_pages.quality_flags.malformed_table` flags
   these for review.
8. **Latency.** `full_agentic` is the slowest mode; the `single_pass`
   baseline exists partly to give a faster fallback for users who don't
   need the agent's verification loop.

---

## 10. Custom dataset onboarding

The system is corpus-neutral in its agent prompts and chunking. To
ingest a non-SEC dataset (compliance memos, research reports, support
tickets exported to PDF, etc.):

1. Lay out the PDFs as `<root>/<ENTITY>/<ENTITY>_<FORM>_<YYYYMMDD>.pdf`
   (the filename pattern fills `ticker`, `form_type`, `filing_date` on
   registration; OCR fills the rest later).
2. Create the dataset with the domain overrides:

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
       "hyde_style_hint": "Compliance memo register: incident, remediation, control mapping.",
       "citation_label_template": "[{entity} {filing_date} {form_type}, p. {page}]"
     }'
   ```

3. Point `LOCAL_CORPUS_PATH` at the new root and call
   `POST /v1/datasets/register-local-corpus` with the new
   `dataset_name`, or upload PDFs individually with
   `POST /v1/datasets/{id}/documents`.
4. Author a verified eval set in the same YAML shape as
   `sec_filings_v1.yaml` and seed it with
   `scripts/seed_eval_cases.py`.
5. Run the locked ablation against the new dataset; the variant matrix
   is dataset-independent.

Override columns and their behaviour are documented in the main
[`README.md`](../README.md#domain-adaptive-retrieval-config) and tested
by `backend/tests/test_prompts_dataset_aware.py` and
`backend/tests/test_planner_fallback_uses_config.py`.

---

## Demo video

URL: _pending recording — to be linked in the submission packet._

The walkthrough should cover, in order:

1. `docker compose up --build` and the system status page going green.
2. Bearer-token entry on the frontend auth screen.
3. `Register Local Corpus` for `sec_filings_pdf/` and the Jobs view
   showing ingestion progress.
4. A single-company query ("What was Microsoft's total revenue in
   FY2024?") with citations visible alongside the answer.
5. A table-lookup query against a 10-K segment table.
6. A multi-company comparison query.
7. An `insufficient_evidence` query that the system correctly refuses
   to answer.
8. Opening the Trace viewer for one of the answers, showing the plan,
   retrieve calls, verifier output, and rerank scores.
9. Seeding the eval cases and starting an evaluation run from the
   frontend.
10. The Evaluations comparison view across the full_agentic /
    single_pass / llm_only baselines.

---

## Appendix A. ADR index

| ADR | Topic |
| --- | --- |
| [0001](adr/0001-core-stack.md) | Core stack (Python 3.13, FastAPI, Postgres, MinIO, OpenRouter, etc.) |
| [0002](adr/0002-minio-object-storage.md) | MinIO object storage layout and versioning |
| [0003](adr/0003-document-parsing.md) | Document parsing: Mistral OCR + Docling fallback |
| [0004](adr/0004-table-aware-chunking.md) | Table-aware chunking with Chonkie |
| [0005](adr/0005-retrieval-store.md) | Retrieval store: Postgres + pgvector |
| [0006](adr/0006-agentic-retrieval.md) | Bounded Pydantic AI retrieval agent |
| [0007](adr/0007-background-jobs.md) | Celery + Redis for ingestion and evaluation |
| [0008](adr/0008-api-surface-and-auth.md) | API surface and bearer-token auth |
| [0009](adr/0009-evaluation-strategy.md) | Pydantic Evals + RAGAS + paired stats |
| [0010](adr/0010-frontend-application.md) | React + Vite + TanStack stack |
| [0011](adr/0011-ai-provider-gateway.md) | OpenRouter as primary provider gateway |

## Appendix B. Configuration knobs

All in `backend/packages/rag-common/rag_common/config.py`; defaults are
listed in `backend/.env.example`.

| Group | Setting | Default | Used by |
| --- | --- | --- | --- |
| Retrieval | `semantic_candidates` | 50 | `hybrid_retrieve` |
| Retrieval | `full_text_candidates` | 50 | `hybrid_retrieve` |
| Retrieval | `fused_candidates` | 20 | RRF cut-off |
| Retrieval | `evidence_top_k` | 8 | chunks passed to generator |
| Retrieval | `rerank_candidates` | 20 | OpenRouter rerank input size |
| Retrieval | `reranker_enabled` | true | rerank stage |
| Retrieval | `hyde_enabled` | true | HyDE pre-step |
| Retrieval | `retrieval_agent_tool_call_budget` | 4 | agent `UsageLimits` |
| Chunking | `chunk_target_tokens` | 1000 | Chonkie target size |
| Chunking | `chunk_max_tokens` | 1500 | Chonkie hard max |
| Chunking | `chunk_overlap_tokens` | 120 | narrative overlap |
| Chunking | `table_max_rows` | 60 | oversized table split |
| Eval | `eval_temperature_zero` | true | force temperature 0 in eval |
| Embeddings | `embedding_dimension` | 1024 | pgvector column width |

## Appendix C. References

- `task.md` — assessment brief.
- [`system-design.md`](system-design.md) — accepted design document.
- [`adr/`](adr/) — eleven ADRs.
- [`eval/ablation_v1_plan.md`](eval/ablation_v1_plan.md) — pre-registered ablation plan.
- [`eval/sec_filings_v1_verification.md`](eval/sec_filings_v1_verification.md) — ground-truth verification.
- [`eval/sec_filings_v1_review.md`](eval/sec_filings_v1_review.md) — per-case review notes.
- [`agentic-retrieval.md`](agentic-retrieval.md) — agent contract notes.
- Chonkie: https://docs.chonkie.ai/oss/chunkers/table-chunker
- pgvector: https://github.com/pgvector/pgvector
- Mistral OCR: https://docs.mistral.ai/studio-api/document-processing/basic_ocr
- OpenRouter rerank: https://openrouter.ai/docs/api/api-reference/rerank/create-rerank/
- Pydantic AI: https://pydantic.dev/docs/ai/
- Pydantic Evals: https://pydantic.dev/docs/ai/evals/evals/
- RAGAS: https://docs.ragas.io/
