# ADR-0005: Retrieval Store

## Status

Accepted

## Context

The initial corpus is modest for a single-node database: 50 ticker folders and 337 PDFs. The system still requires robust retrieval, metadata filtering, table handling, citations, and custom dataset ingestion.

The project stack specifies Postgres plus pgvector.

## Decision

Use Postgres as the durable system of record and pgvector for semantic search.

Store document metadata, page text, chunks, embeddings, ingestion jobs, query traces, citations, and evaluation results in Postgres. Store large raw artifacts in MinIO and reference them by object key/version.

Use hybrid retrieval:

- pgvector semantic search over chunk embeddings.
- Postgres full-text search over normalized chunk text.
- Metadata filters for ticker, form type, filing date, report period, page, and dataset.
- Reciprocal rank fusion to merge semantic and lexical candidate lists.
- OpenRouter reranking over fused candidates when enabled by configuration.

## Consequences

- The system has one transactional metadata store and one object store.
- pgvector HNSW indexes can support fast local search while exact search remains available for recall checks.
- Full-text search improves ticker, metric, and phrase retrieval where embeddings alone are weak.
- Retrieval tuning can be evaluated without changing the storage architecture.
- The active vector index is tied to the configured OpenRouter embedding model and dimension; changing that model requires reindexing.

## Data Model Areas

The implementation should model these logical entities:

- Dataset.
- Document.
- Document version/source object.
- Parsed page.
- Chunk.
- Embedding.
- Ingestion job.
- Query trace.
- Evidence/citation.
- Evaluation dataset, case, run, and result.

## Alternatives Considered

- Managed vector database: rejected because the project standardizes on Postgres/pgvector and the corpus size does not require external vector infrastructure.
- FAISS only: rejected because metadata filtering, durability, and evaluation traces are easier in Postgres.
- Separate table database: rejected for v1 because table-aware chunks meet the current requirement.

## References

- pgvector HNSW and hybrid search: https://github.com/pgvector/pgvector
- OpenRouter embeddings: https://openrouter.ai/docs/api/reference/embeddings
- OpenRouter rerank API: https://openrouter.ai/docs/api/api-reference/rerank/create-rerank/
