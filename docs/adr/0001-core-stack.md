# ADR-0001: Core Stack

## Status

Accepted

## Context

The project requires a production-grade RAG system over SEC filing PDFs. The chosen stack is Python 3.13, FastAPI, Pydantic AI, Docker Compose, Postgres with pgvector, SQLAlchemy, Alembic, Ruff, mypy, pytest, Pydantic settings/secrets, Pydantic Evals, RAGAS/DeepEval, OpenRouter, Mistral AI OCR, Docling as fallback, React, Vite, Tailwind CSS, TypeScript, React Query, shadcn/ui, React Hook Form, and Zod.

The design also needs durable document storage, asynchronous ingestion, and table-aware chunking.

## Decision

Use the chosen project stack as the primary implementation stack.

Add these supporting components:

- MinIO for S3-compatible document and parser-artifact storage.
- Celery plus Redis for long-running ingestion and evaluation jobs.
- Chonkie for table-aware chunking rules.

Use OpenRouter as the primary AI gateway for LLM, embedding, and reranking services. Use direct Mistral integration for OCR only.

Use React, Vite, Tailwind CSS, TypeScript, React Query, shadcn/ui, React Hook Form, and Zod for a focused web application that exercises the backend workflows.

Do not add a notebook-first workflow or CLI as part of the initial implementation.

## Consequences

- The system remains aligned with the project stack while adding only components needed for reproducible ingestion, long-running OCR/indexing work, and the frontend operator workflow.
- Docker Compose must run at least FastAPI, a frontend dev/static service, Postgres/pgvector, MinIO, Redis, and one or more Celery workers.
- Redis is infrastructure for Celery only. Postgres remains the durable system of record.
- Extra dependencies must be justified in the report as design choices, not incidental additions.

## Alternatives Considered

- Minimal stack only: rejected because long-running OCR and reproducible artifact storage would be weaker.
- Provider/tool agnostic stack: rejected for v1 because the project standardizes on OpenRouter for most AI services and benefits from a focused, explainable design.
- Backend-only application: rejected because the project includes a frontend stack and benefits from a clear operator UI.

## References

- Pydantic AI OpenRouter provider: https://pydantic.dev/docs/ai/models/openrouter/
- OpenRouter API reference: https://openrouter.ai/docs/api-reference/overview/
- FastAPI security primitives: https://fastapi.tiangolo.com/tutorial/security/first-steps/
- Celery Redis broker/backend: https://docs.celeryq.dev/en/v5.6.3/getting-started/backends-and-brokers/redis.html
- Vite React TypeScript templates: https://vite.dev/guide/
- Tailwind CSS with Vite: https://tailwindcss.com/docs
- shadcn/ui with Vite: https://ui.shadcn.com/docs/installation/vite
