# rag-common

Shared kernel for the SEC filings RAG benchmark workspace.

Contains configuration, database models, Pydantic schemas, MinIO object store
helpers, the OpenRouter provider client, and centralized Celery task/queue
name constants. Consumed by `rag-benchmarking`, `rag-ingestion-worker`,
`rag-retrieval`, and `rag-evaluation`.
