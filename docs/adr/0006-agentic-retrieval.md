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

## Update: Tool-Using Retrieval Agent (May 2026)

The original decision standardized on three sequential Pydantic AI agents (planner /
verifier / generator) producing structured JSON. None of those agents used tools - the
ADR's "local tools" were Python functions invoked by the orchestrator, not by the LLM.
In practice this meant the verifier's `retry_query` was the only adaptive behavior, and
subquestion decomposition was decorative because retrieval ran once on the original
question regardless of how the planner decomposed it.

This revision folds the planner, retrieval, and verifier roles for `full_agentic` mode
into a single bounded **tool-using** agent that exposes one tool, `retrieve_evidence`.
The agent decides how many times and with what filters to call it (up to
`retrieval_agent_tool_call_budget`, default 4), and emits a structured output that
combines what the planner and verifier used to produce separately:

- `selected_chunk_ids` (replaces the verifier's supported_chunk_ids)
- `missing_subclaims` and `contradictions` (now also forwarded to the generator prompt)
- `target_tickers`, `forms`, `metrics`, `query_type`, `latest`, `subquestions` (planner
  metadata, retained for trace and generator-prompt hints)

Internally, `retrieve_evidence` runs HyDE (Hypothetical Document Embeddings) when the
LLM enables it via the `use_hyde` parameter (default `True`), then hybrid retrieval
(pgvector + Postgres FTS + RRF), then optional reranking. HyDE uses the chat agent to
draft a hypothetical SEC-filing-style passage, which is embedded for the vector probe
while FTS keeps using the literal user query - this aligns the vector probe with
filing-style register without losing lexical anchors.

The bounded-loop guarantees are preserved: at most N tool calls (enforced by
`UsageLimits(request_limit=N+1)`), deterministic fallback to `infer_query_plan` +
single `hybrid_retrieve` + `keyword_verify_evidence` when the chat agent is unavailable
or raises, ticker/form whitelisting inside the tool so the LLM cannot inject filters
that escape the dataset's known set, and a single generator step downstream.

`single_pass` and `llm_only` ablation modes are unchanged so the comparison table in
the evaluation report stays meaningful.

The new modules: `rag_retrieval/hyde.py`, `rag_retrieval/retrieval_tool.py`. The
verifier-driven retry block in `run_query` is removed - the agent's tool-call
iteration replaces it.

## References

- Pydantic AI OpenRouter provider: https://pydantic.dev/docs/ai/models/openrouter/
- OpenRouter chat completions: https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request
- HyDE paper (Gao et al., 2022): https://arxiv.org/abs/2212.10496
