# SEC Filings Agentic RAG System Design

## Status

Accepted design for implementation.

This document converts the product requirements, technology choices, and accepted ADRs into an implementation-ready system design. It intentionally defines architecture, interfaces, data flow, and evaluation approach only. It does not include application code.

## Goals

- Build a production-grade RAG system over SEC filing PDFs for an initial large-cap company corpus and similar custom datasets.
- Answer investor-style questions with accurate, source-grounded responses and page-level citations.
- Handle narrative text and financial tables without splitting table meaning during chunking.
- Support robust retrieval for single-document, cross-document, multi-part, and "latest filing" questions.
- Provide a focused web application for document ingestion, querying, citation inspection, traces, and evaluation runs.
- Provide reproducible ingestion, evaluation, and ablation results for project reporting.
- Keep implementation aligned with the project stack: Python 3.13, FastAPI, Pydantic AI, Postgres/pgvector, OpenRouter, Mistral AI OCR, SQLAlchemy, Alembic, pytest, Ruff, mypy, Pydantic Evals, RAGAS/DeepEval, Docker Compose, React, Vite, Tailwind CSS, TypeScript, React Query, shadcn/ui, React Hook Form, and Zod.

## Non-Goals

- No marketing site or broad consumer-facing investment product in v1.
- No live SEC fetching at query time.
- No personalized financial advice.
- No normalized financial statement database in v1.
- No full user/role management in v1.

## Context

The initial corpus currently contains 50 ticker folders and 337 PDFs. Most tickers have recent 10-K, 10-Q, and 8-K filings; at least one ticker has fewer files. The system must not assume every ticker has a complete or uniform filing set.

Queries such as "latest 10-K" or "last reported fiscal year" must be interpreted against the ingested dataset, not live external data. The response should make the filing date/report period explicit when that affects the answer.

## Architecture Overview

Primary services:

| Component | Responsibility |
| --- | --- |
| React/Vite frontend | Web workspace for datasets, ingestion, query, traces, and evaluations. |
| FastAPI app | Authenticated HTTP API for datasets, documents, ingestion jobs, queries, traces, and evaluations. |
| Celery workers | Long-running ingestion (parsing, chunking, embedding, indexing). |
| In-process evaluation runner | Daemon thread per evaluation launched inside the FastAPI process (`rag_benchmarking.evaluation.launch_evaluation_thread`); RAGAS and judge calls run in the API image. |
| Redis | Celery broker and result backend only. |
| Postgres + pgvector | Durable metadata, chunks, embeddings, traces, jobs, citations, and evaluation results. |
| MinIO | Raw PDFs and parser artifacts. |
| OpenRouter | Primary gateway for LLM, embedding, reranking, and LLM-judged evaluation calls. |
| Mistral AI | Direct OCR provider for SEC filing PDF parsing. |
| Docling | Parser fallback and optional parser comparison path. |
| Chonkie | Table-aware chunking of Markdown/text output. |

High-level flow:

1. Register dataset and upload or register PDFs through the API.
2. Store raw PDFs in MinIO with versioning and checksums.
3. Start ingestion jobs through Celery.
4. Parse PDFs with Mistral OCR, falling back to Docling on failures or quality checks.
5. Store parser artifacts in MinIO.
6. Chunk parsed pages with Chonkie, preserving table boundaries.
7. Embed chunks with the configured OpenRouter embedding model and store chunks/embeddings in Postgres.
8. Query through a bounded Pydantic AI retrieval agent.
9. Rerank candidates and synthesize answers through OpenRouter-backed models.
10. Evaluate with Pydantic Evals plus RAGAS/DeepEval and store results.
11. Inspect datasets, answers, citations, traces, jobs, and evaluations through the React web app.

## ADR Index

- [ADR-0001: Core Stack](adr/0001-core-stack.md)
- [ADR-0002: MinIO Object Storage](adr/0002-minio-object-storage.md)
- [ADR-0003: Document Parsing](adr/0003-document-parsing.md)
- [ADR-0004: Table-Aware Chunking](adr/0004-table-aware-chunking.md)
- [ADR-0005: Retrieval Store](adr/0005-retrieval-store.md)
- [ADR-0006: Agentic Retrieval](adr/0006-agentic-retrieval.md)
- [ADR-0007: Background Jobs](adr/0007-background-jobs.md)
- [ADR-0008: API Surface, Web App, And Auth](adr/0008-api-surface-and-auth.md)
- [ADR-0009: Evaluation Strategy](adr/0009-evaluation-strategy.md)
- [ADR-0010: Frontend Application](adr/0010-frontend-application.md)
- [ADR-0011: AI Provider Gateway](adr/0011-ai-provider-gateway.md)

## Storage Design

### MinIO Buckets And Keys

MinIO is the canonical document store for ingestion. Local files are only seed inputs.

Use bucket versioning for raw documents. Store parser artifacts under deterministic ingestion-run paths.

Recommended object layout:

| Object Type | Key Pattern |
| --- | --- |
| Raw PDF | `raw/{dataset_id}/{ticker}/{form_type}/{filing_date}/{checksum}.pdf` |
| OCR response | `artifacts/{dataset_id}/{document_id}/{run_id}/ocr.json` |
| Parsed page Markdown | `artifacts/{dataset_id}/{document_id}/{run_id}/pages/{page_number}.md` |
| Extracted table metadata | `artifacts/{dataset_id}/{document_id}/{run_id}/tables/{page_number}.json` |
| Eval artifacts | `artifacts/{dataset_id}/evals/{eval_run_id}/...` |

Every stored document row must keep the MinIO bucket, object key, version id, content checksum, and byte size.

### Postgres Logical Model

The implementation should model these entities:

| Entity | Key Fields |
| --- | --- |
| Dataset | id, name, description, created_at, default query settings, domain_label, entity_label, valid_forms, metric_terms, hyde_style_hint, citation_label_template. The last six are nullable overrides for the agent prompts and the deterministic-planner fallback; nulls resolve to SEC defaults in `rag_retrieval.dataset_config`, so the SEC corpus is one instance rather than the hard-coded identity. |
| Document | id, dataset_id, ticker, company_name, form_type, filing_date, report_period, fiscal_year, fiscal_quarter, checksum, MinIO source reference. |
| Ingestion run | id, dataset_id, document_id, parser config, chunking config, embedding model, status, timings, error summary. |
| Parsed page | document_id, page_number, parser, artifact key, text stats, table count, quality flags. |
| Chunk | id, document_id, page_start, page_end, text, normalized text, contains_table, token count, metadata, source offsets. |
| Embedding | chunk_id, provider, model, dimension, vector, created_at. |
| Query trace | id, dataset_id, user question, plan, retrieval calls, verifier result, model/provider metadata, final answer metadata. |
| Citation | trace_id, chunk_id, document_id, page_number, evidence text, citation label. |
| Eval case | id, dataset_id, question, expected answer, expected citations/pages, tags. |
| Eval run/result | run config, system variant, model/provider metadata, metrics, per-case outputs, errors. |

Indexes should support:

- Dataset-scoped document lookup.
- Ticker/form/filing date filtering.
- Full-text search over chunk text.
- HNSW vector search over embeddings.
- Trace and eval lookup by run id.

The active retrieval index uses one configured OpenRouter embedding model and vector dimension at a time. Changing the embedding model requires a new indexing run because vector dimensions and semantic spaces can differ between models.

## Ingestion Design

### Document Registration

The API accepts either PDF uploads or existing MinIO object references. For the initial local corpus, an admin ingestion endpoint can register files from the configured dataset path, upload each file to MinIO, and register document metadata.

Filename-derived metadata can initialize ticker, form type, and filing date. Parser-derived metadata can later enrich company name, fiscal year, fiscal quarter, and report period. The system must allow metadata correction without re-uploading the raw PDF.

### Ingestion Job Flow

1. API creates an ingestion job and durable run record.
2. Celery worker reads the raw PDF from MinIO.
3. Worker sends the PDF to Mistral OCR.
4. Raw OCR response is written to MinIO.
5. Parser quality checks run per page.
6. Pages that fail checks are retried with Docling fallback.
7. Page Markdown/text and table metadata are written to MinIO.
8. Chonkie chunks parsed content with table boundaries protected.
9. OpenRouter embeddings are generated in batches with the configured embedding model.
10. Chunks and embeddings are committed to Postgres.
11. Job status is marked complete with counts, timings, and artifact references.

### Idempotency

Document registration is idempotent by dataset id plus content checksum. Re-ingesting the same document creates a new ingestion run only when parsing, chunking, or embedding configuration changes.

Chunk and embedding rows must be tied to an ingestion run so older runs can be compared, disabled, or deleted without losing raw document history.

### Parser Quality Rules

Flag a page for fallback or manual review when:

- Extracted text is empty or below minimum length.
- The page has many numeric tokens but no table block.
- A Markdown table is malformed.
- Page numbering is inconsistent.
- OCR response lacks required page metadata.

## Chunking Design

Tables stay inline with the surrounding filing text wherever possible. A protected-region pass identifies Markdown or HTML table blocks before normal chunking.

Initial chunking defaults:

| Setting | Default |
| --- | --- |
| Target chunk size | 800 to 1,200 tokens |
| Hard max chunk size | 1,500 tokens |
| Narrative overlap | 100 to 150 tokens |
| Oversized table strategy | Split by row group, repeat header |
| Chunk provenance | document id, page range, object version, parser, offsets |

Chunk types:

- Narrative chunk: prose only.
- Table chunk: table only, usually for large tables.
- Mixed chunk: nearby heading/prose plus table, when it fits the budget.

Chunk text should include table captions/headings when available, because those terms are often required for retrieval.

## Retrieval Design

### Retrieval Agent (full_agentic mode)

For the `full_agentic` retrieval mode, a single Pydantic AI tool-using agent absorbs
the planner, retrieval, and verifier responsibilities. The agent exposes exactly one
tool, `retrieve_evidence`, and decides when, how many times, and with what filters to
call it. The bounded budget is enforced via `UsageLimits(request_limit=N+1)` with
`N = retrieval_agent_tool_call_budget` (default 8).

The agent's static identity is corpus-neutral ("filings RAG system"). At every run,
`@agent.instructions` injects a per-dataset block containing `CORPUS: <domain_label>`,
`KNOWN_FORMS: <valid_forms>`, and `KNOWN_TICKERS: <…>` resolved from the `DatasetConfig`
loaded once in `run_query`. The same pattern is used by the planner, HyDE, verifier,
and generator agents so the SEC corpus and any registered custom dataset share one
prompt surface.

The agent's final structured output combines planner-style metadata (target tickers,
forms, metrics, query_type, latest, subquestions, reasoning) with verifier-style
signals (`selected_chunk_ids`, `missing_subclaims`, `contradictions`, `confidence`,
`insufficient_evidence`). The generator step downstream sees the verifier signals and
hedges accordingly.

`retrieve_evidence` parameters:

| Parameter | Purpose |
| --- | --- |
| `query` | Free-form text. FTS uses this verbatim; HyDE-expanded text is used for the vector probe. |
| `tickers` | Restrict to known tickers (unknown tickers are silently dropped). |
| `form_types` | Subset of {10-K, 10-Q, 8-K}; invalid forms are dropped. |
| `filing_date_start` / `filing_date_end` | ISO date bounds on filing_date. |
| `top_k` | 1 to 12; capped server-side. |
| `use_hyde` | When True, generate a hypothetical SEC-filing passage with the chat model and embed that for the vector probe. Default True. |

When the chat agent is unavailable (`ALLOW_MOCK_PROVIDERS=true`, missing key, or
upstream failure) the orchestrator falls back to a single deterministic pass:
`infer_query_plan` -> `hybrid_retrieve` -> `keyword_verify_evidence`. The fallback path
honors the same `AgentRetrievalResult` shape so downstream code is uniform.

The `single_pass` mode uses the heuristic planner and a single `hybrid_retrieve` with
no HyDE and no agent, preserving a meaningful non-agentic baseline. The `llm_only`
mode is unchanged.

### Query Planning (legacy planner; used by single_pass + fallback)

The legacy planner converts the user question into a structured retrieval plan. It is
the planning step for `single_pass` mode and the heuristic fallback path; for
`full_agentic` mode the retrieval agent does its own planning via tool-call decisions.

| Field | Purpose |
| --- | --- |
| target companies/tickers | Metadata filter candidates. |
| forms | 10-K, 10-Q, 8-K, or no restriction. |
| time constraints | Fiscal year, latest filing, latest 10-K, date range. |
| metrics/topics | Revenue, debt, R&D, AI demand, segment results, risk factors, etc. |
| query type | Fact lookup, table lookup, comparison, trend, thematic synthesis, insufficient evidence. |
| ambiguity | Whether clarification or explicit assumption is needed. |

### Candidate Retrieval

Run hybrid retrieval:

1. Apply dataset and metadata filters.
2. Run pgvector semantic search.
3. Run Postgres full-text search.
4. Merge results with reciprocal rank fusion.
5. Prefer diversity by document/page for broad thematic queries.
6. Rerank fused candidates with the configured OpenRouter rerank model when enabled.

Initial retrieval defaults:

| Setting | Default |
| --- | --- |
| Semantic candidates | 50 |
| Full-text candidates | 50 |
| Fused candidates before verification | 20 |
| Evidence chunks passed to generator | 6 to 10 |
| Rerank candidates | 20 |
| Agent retry budget | One retry |

### Evidence Verification

Before generation, the agent verifies whether retrieved chunks answer each subquestion. Verification outputs:

- Supported subclaims.
- Missing subclaims.
- Contradictions or ambiguous evidence.
- Recommended retry query if needed.

If evidence is insufficient after one retry, the final answer must say so directly and cite any partial evidence used.

If OpenRouter reranking fails, the system should degrade to reciprocal-rank-fusion order, record the degradation in the query trace, and continue.

### Answer Generation

The generator receives only verified evidence and citation metadata. It runs through the configured OpenRouter chat model and must:

- Answer from retrieved evidence only.
- Cite every material claim.
- Include page-level citations.
- Avoid unsupported current-market or live-data claims.
- For investment recommendation questions, provide an evidence-based comparison and limitations, not individualized advice.

Citation format in API responses is structured. Human-readable rendering can use labels such as `[AAPL 2025 10-K, p. 23]`.

## API Design

All non-health endpoints require Bearer token authentication. The React web app consumes these endpoints; the API remains the stable integration contract for tests, evals, and direct HTTP usage.

**Single-tenant trust model.** `API_BEARER_TOKEN` is a single shared credential with full read/write/delete authority over every dataset, document, ingestion job, and evaluation run in the deployment. There is no per-user / per-dataset ownership. In particular, any holder of the token can mutate any dataset's `domain_label`, `entity_label`, `hyde_style_hint`, and other prompt-shaping overrides via `PATCH /v1/datasets/{id}`; those overrides are then injected into every LLM agent call against that dataset and affect *all* subsequent queries from any caller. Treat the token as a high-privilege secret — do not share it across users who should not be able to influence each other's query results.

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/datasets` | Create dataset namespace. |
| `GET /v1/datasets` | List datasets. |
| `GET /v1/datasets/{dataset_id}` | Read dataset details. |
| `POST /v1/datasets/{dataset_id}/documents` | Upload/register one or more PDFs. |
| `GET /v1/datasets/{dataset_id}/documents` | List documents and ingestion status. |
| `POST /v1/datasets/{dataset_id}/ingestions` | Start ingestion for documents or a MinIO prefix. |
| `GET /v1/jobs/{job_id}` | Read job status, progress, errors, and artifact links. |
| `POST /v1/query` | Ask a question against a dataset. |
| `GET /v1/traces/{trace_id}` | Read retrieval and generation trace when enabled. |
| `POST /v1/evaluations` | Start evaluation run. |
| `GET /v1/evaluations/{eval_run_id}` | Read aggregate and per-case eval results. |
| `GET /health` | Process liveness. |
| `GET /ready` | Dependency readiness. |

### Query Request

Required fields:

- `dataset_id`
- `question`

Optional fields:

- `filters`: ticker, form type, filing date range, report period, document ids.
- `top_k`: override evidence count within configured bounds.
- `include_trace`: include or persist detailed agent trace.
- `retrieval_mode`: full agentic, single-pass baseline, or LLM-only ablation.

### Query Response

Required fields:

- `answer`
- `citations`
- `evidence`
- `trace_id`
- `confidence`

Citation fields:

- `document_id`
- `ticker`
- `form_type`
- `filing_date`
- `report_period`
- `page_number`
- `chunk_id`
- `minio_bucket`
- `minio_key`
- `minio_version_id`
- `snippet`

If the system cannot answer:

- `answer` states that evidence is insufficient.
- `insufficiency_reason` explains what was missing.
- `citations` includes partial evidence only when useful.

## Frontend Design

The frontend is a React + Vite + TypeScript single-page application. It is an operator workspace for the backend system, not a marketing site.

### Frontend Responsibilities

The web app must support:

| View | Purpose |
| --- | --- |
| Dataset overview | Show document counts, ingestion coverage, index status, and latest activity. |
| Document management | Upload/register PDFs, review parsed metadata, and start ingestion. |
| Job monitor | Show Celery job progress, retries, failures, and parser/indexing artifacts. |
| Query workspace | Ask questions with filters, retrieval mode, answers, citations, evidence, and insufficient-evidence states. |
| Trace viewer | Inspect query plan, retrieval candidates, verifier output, retries, and final evidence. |
| Evaluation dashboard | Start eval runs and compare aggregate, per-case, and ablation metrics. |
| Settings/status | Show backend, Postgres, MinIO, Redis/Celery, and model configuration health. |

### Frontend Stack Usage

Use the frontend stack this way:

| Tool | Role |
| --- | --- |
| React + Vite | SPA runtime, local dev server, and production static build. |
| TypeScript | Typed components, API models, and client utilities. |
| Tailwind CSS | Utility styling and layout. |
| shadcn/ui | Tables, tabs, forms, dialogs, buttons, badges, toasts, skeletons, and status components. |
| React Query | API fetching, mutation state, cache invalidation, job polling, and eval polling. |
| React Hook Form | Upload, ingestion, query, filter, and eval configuration forms. |
| Zod | Client-side form validation and API response/request schema checks. |

### Data Flow

The frontend talks only to FastAPI. It does not call MinIO, OpenRouter, Mistral, Postgres, Redis, or Celery directly.

React Query owns server state. Forms validate with Zod before calling API mutations. Long-running ingestion and evaluation pages poll `GET /v1/jobs/{job_id}` or `GET /v1/evaluations/{eval_run_id}` until terminal state.

API schemas should be represented in the frontend as Zod schemas, either generated from OpenAPI or maintained in a shared frontend API layer. Schema drift should fail tests or visible runtime validation in development.

### Frontend Deployment

In local development, Docker Compose runs the Vite dev server as a separate `frontend` service that talks to FastAPI through the configured API base URL. CORS is enabled only for the configured frontend origin.

For the packaged deployment, the SPA is built to static assets and served by FastAPI. This avoids adding Nginx/Caddy or another production web server in v1.

### Auth And Session Handling

The web app uses the same Bearer token as the API.

For local development and internal deployments, the token can be entered in a setup/auth screen and kept in memory or session storage. Do not hardcode tokens in the frontend bundle. A production deployment can replace this with real user authentication later without changing the backend RAG APIs.

### UI Principles

- Keep the UI dense, quiet, and operational.
- Prefer tables, filters, tabs, segmented controls, and explicit status indicators over decorative layouts.
- Keep citations and evidence visible beside or directly below answers.
- Show parser failures, retry status, insufficient evidence, and eval failures as first-class states.
- Avoid nested cards, oversized hero sections, decorative backgrounds, and instructional copy that repeats obvious UI behavior.

## AI Provider Design

OpenRouter is the primary AI gateway for chat, embeddings, reranking, and LLM-judged evaluations. Direct Mistral integration is reserved for OCR in the document parsing pipeline.

Model roles are configured independently:

| Role | Provider | Purpose |
| --- | --- | --- |
| `chat_model` | OpenRouter | Agent planning, verification, and answer synthesis. |
| `judge_model` | OpenRouter | RAGAS/DeepEval or other LLM-judged evaluation checks. |
| `embedding_model` | OpenRouter | Chunk and query embeddings for pgvector retrieval. |
| `rerank_model` | OpenRouter | Reranking fused semantic/full-text candidates. |
| `ocr_model` | Direct Mistral | PDF OCR and page/table extraction. |

The implementation should use Pydantic AI's OpenRouter provider for the agent LLM. Embedding and reranking calls can use a small typed OpenRouter client because they are retrieval services rather than agent chat turns.

Every ingestion run, query trace, and evaluation run must record the model ids, resolved provider metadata when available, token/search-unit usage, and cost metadata when returned by the provider.

Routing defaults:

- Require explicit OpenRouter model ids for chat, embeddings, and reranking.
- Allow OpenRouter provider fallbacks for availability.
- Require provider support for structured-output/tool parameters on requests that depend on them.
- Prefer provider data-collection setting `deny` where supported.
- Treat embedding model changes as a reindexing event.

## Evaluation Design

Use Pydantic Evals as the evaluation runner. Use deterministic evaluators for retriever and citation checks, and RAGAS/DeepEval for faithfulness and answer quality where LLM judging is appropriate. LLM-judged checks use the configured OpenRouter judge model.

### Eval Dataset

Target 60 to 80 curated cases:

| Case Type | Examples |
| --- | --- |
| Single-company lookup | Total revenue, long-term debt, cash balance. |
| Table lookup | Segment revenue, product revenue, gross margin table values. |
| Trend | Three-year gross margin or R&D trend. |
| Cross-company comparison | R&D as percentage of revenue for two companies. |
| Sector synthesis | AI-related demand across semiconductor companies. |
| Multi-part | Compare revenue growth and risk discussion across several companies. |
| Latest filing | Latest 10-K or latest available quarterly filing in dataset. |
| Refusal/insufficient evidence | Ask for information outside the ingested corpus. |

Ground truth should include expected answer, expected source document, expected page number where possible, and tags for slicing results.

### Metrics

Retriever:

- Recall@k.
- MRR.
- Page-level evidence F1.
- Metadata filter correctness.

Generator:

- Exact or normalized numeric accuracy.
- Citation coverage.
- Citation validity.
- Faithfulness.
- Insufficient-evidence correctness.

System:

- Query latency.
- Ingestion time per document.
- OCR failure/fallback rate.
- Token usage and estimated provider cost.

### Ablations

Run the same eval cases against:

- Full agentic RAG.
- Single-pass hybrid retrieval without retry/verifier.
- LLM-only with no retrieved context.

Report aggregate scores and representative failures. Do not hide failure modes; use them to justify future improvements.

## Configuration

Use Pydantic settings/secrets for startup validation.

Required configuration groups:

| Group | Examples |
| --- | --- |
| API | API token, environment, CORS if needed. |
| Database | Postgres URL, pool settings. |
| MinIO | endpoint, access key, secret key, bucket names, secure flag. |
| Redis/Celery | broker URL, result backend URL, queue names. |
| OpenRouter | API key, chat model, judge model, embedding model, rerank model, routing preferences, data-collection preference. |
| Mistral OCR | OCR model and (optional) API key. Without the key, parsing transparently falls back to docling. |
| Frontend | API base URL, public app environment, optional default dataset id, feature flags. |
| Retrieval | candidate counts, top_k, retry budget, reranker flag. |
| Chunking | chunk size, overlap, table max rows/tokens. |
| Evaluation | eval dataset, evaluator settings, output paths, timeout. |

Configuration defaults should be safe for local Docker Compose, but missing secrets must fail fast at startup.

## Security And Privacy

- Require Bearer token auth for all operational endpoints.
- Do not log full API keys, bearer tokens, or raw document contents in application logs.
- Do not hardcode Bearer tokens into frontend builds; local sessions may store tokens in memory or session storage only.
- Store raw documents and parser artifacts in MinIO, not local temp folders beyond short-lived processing.
- Limit query traces to configured retention, since traces may contain sensitive excerpts for custom datasets.
- Keep MinIO and Redis private to the Docker network in local deployment unless explicitly exposed for development.

## Observability

Record structured logs for:

- Document registration.
- OCR request start/end/failure.
- Parser fallback.
- Chunk and embedding counts.
- Query trace id and retrieval mode.
- Evaluation run id and aggregate metrics.
- Frontend-visible request failures, job terminal states, and eval terminal states.
- OpenRouter model ids, resolved provider metadata, token/search-unit usage, and provider degradation/fallback events.

Persist query traces in Postgres when `include_trace` is true or when evaluation is running. Traces should include the plan, retrieval candidates, verification result, final evidence, model names, and timing.

## Failure Handling

| Failure | Behavior |
| --- | --- |
| Duplicate upload | Reuse existing raw object by checksum or create new version if content changed. |
| OCR provider timeout | Retry with backoff. |
| OCR malformed output | Store failed artifact and attempt Docling fallback. |
| Docling fallback failure | Mark page/document ingestion failed with actionable error. |
| Embedding batch failure | Retry batch; do not partially mark ingestion complete. |
| OpenRouter chat failure | Retry with backoff, then return a structured provider error. |
| OpenRouter query embedding failure | Return a structured query failure rather than using stale vectors. |
| OpenRouter rerank failure | Continue with reciprocal-rank-fusion order and record the degradation in the trace. |
| Retrieval returns weak evidence | Retry once with rewritten retrieval query. |
| Evidence still insufficient | Return insufficient-evidence answer. |
| Citation source missing | Fail generation validation and return internal error in non-eval mode. |

## Implementation Phases

1. Documentation and ADRs.
2. Project scaffold, Docker Compose, settings validation, and health checks.
3. Postgres schema and Alembic migrations.
4. MinIO document registration and raw upload.
5. Celery ingestion skeleton with job status.
6. Mistral OCR parsing and artifact persistence.
7. Chonkie table-aware chunking.
8. OpenRouter embeddings and pgvector indexing.
9. Hybrid retrieval and metadata filtering.
10. OpenRouter reranking.
11. Pydantic AI bounded retrieval agent backed by OpenRouter chat models.
12. Strict citation validation and answer generation.
13. React/Vite frontend scaffold, API client, layout, and auth/session handling.
14. Frontend dataset, ingestion, query, trace, and evaluation views.
15. Evaluation dataset and ablation runner.
16. Report and README user guide.

## Acceptance Criteria

The implemented system is acceptable when:

- A fresh Docker Compose environment can ingest the initial corpus from local files into MinIO and Postgres.
- Re-running ingestion on unchanged PDFs is idempotent.
- Query responses include page-level citations tied to MinIO object versions.
- Table-based questions retrieve table-bearing evidence without broken header/value relationships.
- "Latest" questions resolve against dataset filing dates and state the relevant filing/report period.
- The system returns insufficient-evidence answers rather than hallucinating unsupported facts.
- Query traces record OpenRouter model ids, provider metadata when available, and rerank degradation when applicable.
- Evaluation runs produce retriever, generator, final-answer, and ablation metrics.
- The frontend can register/upload documents, start ingestion, monitor jobs, ask queries, display citations/evidence, inspect traces, and compare evaluation runs.
- The README can explain how to run, reproduce results, and ingest a custom dataset.

## References

- Product requirements and technology choices are maintained in the repository documentation.
- MinIO container documentation: https://min.io/docs/minio/container/index.html
- Mistral OCR documentation: https://docs.mistral.ai/studio-api/document-processing/basic_ocr
- OpenRouter chat completions: https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request
- OpenRouter embeddings: https://openrouter.ai/docs/api/reference/embeddings
- OpenRouter rerank API: https://openrouter.ai/docs/api/api-reference/rerank/create-rerank/
- OpenRouter provider routing: https://openrouter.ai/docs/guides/routing/provider-selection
- Pydantic AI OpenRouter provider: https://pydantic.dev/docs/ai/models/openrouter/
- Pydantic Evals: https://pydantic.dev/docs/ai/evals/evals/
- pgvector: https://github.com/pgvector/pgvector
- Chonkie table chunker: https://docs.chonkie.ai/oss/chunkers/table-chunker
- Celery Redis broker/backend: https://docs.celeryq.dev/en/v5.6.3/getting-started/backends-and-brokers/redis.html
- React project setup guidance: https://react.dev/learn/start-a-new-react-project
- Vite guide: https://vite.dev/guide/
- Tailwind CSS with Vite: https://tailwindcss.com/docs
- shadcn/ui Vite installation: https://ui.shadcn.com/docs/installation/vite
- TanStack Query React docs: https://tanstack.com/query/latest/docs/react/
- React Hook Form resolvers: https://github.com/react-hook-form/resolvers
- Zod documentation: https://zod.dev/
