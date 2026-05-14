# rag-common

Shared kernel for the SEC filings RAG benchmark workspace.

Contains configuration, database models, Pydantic schemas, MinIO object store
helpers, the OpenRouter provider client, and centralized Celery task/queue
name constants. Consumed by `rag-api`, `rag-worker`, `rag-scheduler`, and
`rag-retrieval`.
