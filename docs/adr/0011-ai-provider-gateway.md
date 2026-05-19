# ADR-0011: AI Provider Gateway

## Status

Accepted

## Context

The project now includes OpenRouter and will use it for most AI services, including LLM calls, embeddings, and reranking. The document parsing pipeline still needs Mistral OCR, with Docling as fallback, because OCR is a document-processing concern rather than a general text-generation or ranking service.

The system should avoid scattering provider-specific clients across the codebase. Model choices, routing behavior, cost controls, and usage accounting need to be configurable and traceable.

## Decision

Use OpenRouter as the primary AI gateway for:

- Pydantic AI agent planning, verification, and answer synthesis.
- LLM-judged evaluation steps.
- Chunk and query embeddings.
- Reranking retrieval candidates.

Use direct Mistral integration only for OCR. Keep Docling as local parser fallback. The Mistral key is optional in the boot validator: when unset, `parse_pdf` skips the OCR tier and parses with Docling (then `pypdf` as last resort), so operators with native-text corpora are not forced to provision an OCR provider.

Implement an internal provider layer with explicit service roles:

- `chat_model`: default LLM for planning, verification, and synthesis.
- `judge_model`: model used for faithfulness and qualitative evals.
- `embedding_model`: model used for all active chunk/query embeddings.
- `rerank_model`: model used to rerank fused retrieval candidates.
- `ocr_model`: direct Mistral OCR model.

All model ids must be configuration values. The active model ids, provider routing settings, token/search-unit usage, and upstream provider metadata must be recorded in ingestion runs, query traces, and evaluation results when available.

## Consequences

- Most AI model swaps become configuration changes instead of code changes.
- Query traces and evaluation results can explain which model and route produced each output.
- Embedding model changes require a new indexing run because vector dimensions and semantic spaces can differ between models.
- OCR remains separate from OpenRouter so document parsing quality is not coupled to LLM routing.
- The system must handle OpenRouter rate limits, provider fallback behavior, and usage/cost metadata consistently.

## Routing Defaults

Use these initial defaults unless overridden by environment configuration:

- Require explicit `OPENROUTER_CHAT_MODEL`, `OPENROUTER_EMBEDDING_MODEL`, and `OPENROUTER_RERANK_MODEL`.
- Allow OpenRouter provider fallbacks for availability.
- Require provider support for requested structured-output/tool parameters when a request depends on them.
- Set provider data-collection preference to `deny` where supported.
- Record the final resolved model/provider from every response.

## Failure Behavior

- Chat/model planning failure: retry with backoff, then fail the query with a structured provider error.
- Embedding failure during ingestion: retry batch; do not mark ingestion complete with missing embeddings.
- Embedding failure during query: return a structured query failure rather than falling back to stale vectors.
- Rerank failure: degrade to reciprocal-rank-fusion order, record the degradation in the trace, and continue.
- OCR failure: use the Mistral/Docling fallback behavior defined in ADR-0003.

## Alternatives Considered

- Direct provider clients for every model: rejected because model routing and usage accounting would fragment across the codebase.
- Mistral for all AI services: rejected because OpenRouter is the project gateway for LLM, embedding, and reranking services.
- OpenRouter for OCR: rejected for v1 because the parsing pipeline is built around Mistral OCR and Docling fallback.

## References

- OpenRouter chat completions: https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request
- OpenRouter embeddings: https://openrouter.ai/docs/api/reference/embeddings
- OpenRouter rerank API: https://openrouter.ai/docs/api/api-reference/rerank/create-rerank/
- OpenRouter provider routing: https://openrouter.ai/docs/guides/routing/provider-selection
- Pydantic AI OpenRouter provider: https://pydantic.dev/docs/ai/models/openrouter/
