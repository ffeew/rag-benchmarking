# ADR-0006: Agentic Retrieval

## Status

Accepted

## Context

The system uses agentic RAG and self-correction to improve retrieval quality while preserving reproducibility. The architecture uses local Pydantic AI orchestration, strict grounding, and a bounded quality budget.

The system must remain testable and reproducible. An unconstrained agent loop would make latency, cost, and evaluation harder to control.

## Decision

Use Pydantic AI to orchestrate a bounded local retrieval agent.

The agent uses OpenRouter chat models through Pydantic AI and calls local tools for:

- Query analysis.
- Metadata candidate extraction.
- Hybrid retrieval.
- Evidence verification.
- Retrieval retry with rewritten search terms.
- Final grounded synthesis.

Each query may perform:

- One planning step.
- One initial retrieval round.
- One evidence verification step.
- At most one retrieval retry.
- One final answer step.

## Consequences

- The system uses agentic RAG while preserving deterministic boundaries.
- Query traces can record each step for debugging and evaluation.
- Strict grounding can be enforced before generation.
- Latency and cost are predictable enough for local and hosted deployments.

## Answer Policy

The final answer must:

- Use only verified retrieved evidence.
- Cite every material claim with source document and page.
- State when evidence is insufficient.
- Avoid personalized investment advice; investment-style questions receive evidence-based comparison and limitations.
- Interpret "latest" as latest available in the ingested dataset, not live SEC data.

## Alternatives Considered

- Provider-hosted agent APIs: rejected because local tools and database traces are easier to control in Pydantic AI.
- Deterministic planner only: rejected because the architecture standardizes on agentic retrieval.
- Deep multi-agent loop: rejected for v1 due to latency, cost, and testability.

## References

- Pydantic AI OpenRouter provider: https://pydantic.dev/docs/ai/models/openrouter/
- OpenRouter chat completions: https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request
