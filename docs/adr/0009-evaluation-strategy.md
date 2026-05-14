# ADR-0009: Evaluation Strategy

## Status

Accepted

## Context

The evaluation strategy must measure retrieval quality, answer quality, document processing quality, system behavior, and end-to-end reliability. The benchmark should emphasize recent filings, table retrieval, cross-document synthesis, and citation quality.

The project uses layered evaluation with 60 to 80 cases.

## Decision

Build a layered evaluation system with Pydantic Evals as the orchestration layer and RAGAS/DeepEval for LLM-judged quality checks through OpenRouter-configured judge models.

The evaluation set should contain 60 to 80 curated cases covering:

- Single-company factual lookup.
- Latest filing interpretation.
- Table and numeric extraction.
- Multi-year trends.
- Cross-company comparisons.
- Sector/theme synthesis.
- Multi-part investor questions.
- Ambiguous questions.
- Insufficient-evidence questions.

Compare at least:

- Full agentic RAG.
- Non-agentic single-pass hybrid retrieval.
- LLM-only answer without retrieved context.

## Metrics

Retriever metrics:

- Recall@k.
- MRR.
- Page-level evidence F1.
- Metadata filter correctness.

Generator metrics:

- Ground-truth answer accuracy.
- Citation coverage.
- Citation validity.
- Faithfulness.
- Insufficient-evidence correctness.

System metrics:

- Query latency.
- OCR/indexing time.
- Token usage and provider cost where available.

## Consequences

- Project reporting can make evidence-backed claims about improvement over LLM-only answers.
- Failures will be visible by category instead of hidden by aggregate accuracy.
- Evaluation data must be versioned with source document ids/pages so it remains reproducible.

## Alternatives Considered

- Minimal smoke-test suite: rejected because it would under-support the system's retrieval and answer quality goals.
- Research-grade 100+ case suite: rejected for v1 because it would take time away from implementing the core system.

## References

- Pydantic Evals code-first evaluation: https://pydantic.dev/docs/ai/evals/evals/
