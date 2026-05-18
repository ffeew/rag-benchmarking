# rag-retrieval

Hybrid retrieval, query planning, generation, and verification stack for the
SEC filings RAG benchmark workspace. Consumed by `rag-benchmarking` (live
`/v1/query` and the in-process evaluation runner). Carries the `pydantic-ai`
agent dependency so it stays out of `rag-common`.
