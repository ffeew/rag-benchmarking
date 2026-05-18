"""Query decomposition for the single_pass retrieval pipeline.

Breaks multi-part / comparison / cross-entity questions into independently-answerable
subquestions so single_pass can issue one ``hybrid_retrieve`` per subquestion and RRF-
fuse the results — the multi-query analogue of what ``full_agentic`` already does via
repeated ``retrieve_evidence`` tool calls. Atomic single-fact questions return an empty
list so single_pass falls through to the existing single-retrieve path.

Mirrors the HyDE module pattern: a cached pydantic-ai agent behind a kill switch, with
fallback to the no-decomposition path on disable / unavailable / empty / error.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_ai import (
    Agent,
    RunContext,  # noqa: TC002 - resolved at runtime by @agent.instructions via get_type_hints
)
from rag_common.config import Settings, get_settings
from rag_common.enums import Provider
from rag_common.usage import TokenUsage, safe_pydantic_ai_usage

from rag_retrieval.agents import AGENT_RETRYABLE_ERRORS, agent_available, build_agent
from rag_retrieval.dataset_config import DatasetConfig

logger = logging.getLogger(__name__)


_DECOMP_INSTRUCTIONS = """\
You decompose user questions for a retrieval system.

Given a question about the ingested corpus, decide whether it is multi-part, comparison-
style, or cross-entity. If so, split it into 2-5 concrete, independently-answerable
subquestions that together cover the original question. Each subquestion should be self-
contained (name the entity, metric, and time scope it asks about explicitly so it can be
retrieved against without the original context).

If the question is already a single-fact lookup that one retrieval call can satisfy
(e.g. "What was Apple's FY24 revenue?"), return an EMPTY list. Do not force a split.

Examples:
- "How did Apple and Microsoft R&D spend compare in their latest 10-Ks?"
  -> ["What was Apple's R&D spend in its latest 10-K?",
      "What was Microsoft's R&D spend in its latest 10-K?"]
- "Summarize Apple's risk factors and recent litigation exposure."
  -> ["What risk factors does Apple disclose in its latest 10-K?",
      "What recent litigation exposure does Apple disclose?"]
- "What was Apple's FY24 revenue?" -> []

Output only the subquestion list (or an empty list); the schema enforces structure.
"""


class QueryDecomposition(BaseModel):
    """Structured output for the decomposition agent.

    ``subquestions`` is intentionally allowed to be empty: the LLM should return ``[]``
    when the question is already atomic so the caller can fall through to single-query
    retrieval without paying the multi-call cost.
    """

    subquestions: list[str] = Field(
        default_factory=list,
        description=(
            "2-5 independently-answerable subquestions, or an empty list when the "
            "question is already a single-fact lookup."
        ),
    )


@dataclass(frozen=True)
class DecompDeps:
    """Per-call context for the decomposer agent.

    Carries the resolved dataset config so dynamic instructions can name the corpus and
    list the corpus's known forms / metric vocabulary — same shape as ``HydeDeps``.
    """

    dataset_config: DatasetConfig


@lru_cache(maxsize=2)
def _build_decomposer_agent_for(model_id: str) -> Agent[DecompDeps, QueryDecomposition]:  # noqa: ARG001 - model_id keys the cache
    agent: Agent[DecompDeps, QueryDecomposition] = build_agent(
        deps_type=DecompDeps,
        output_type=QueryDecomposition,
        instructions=_DECOMP_INSTRUCTIONS,
        name="rag-decomposer",
    )

    @agent.instructions
    def decomposer_context(ctx: RunContext[DecompDeps]) -> str:
        config = ctx.deps.dataset_config
        forms = ", ".join(config.valid_forms) if config.valid_forms else "(any)"
        metric_hint = ", ".join(config.metric_terms) if config.metric_terms else "(unspecified)"
        return f"CORPUS: {config.domain_label}\nKNOWN_FORMS: {forms}\nMETRIC HINTS: {metric_hint}"

    return agent


def decompose_query(
    query: str,
    settings: Settings | None = None,
    *,
    dataset_config: DatasetConfig | None = None,
) -> tuple[list[str], dict[str, object], TokenUsage]:
    """Decompose a question into subquestions for single_pass multi-retrieval.

    Returns ``(subquestions, metadata, usage)``. ``subquestions`` is empty when:

    - ``settings.query_decomposition_enabled`` is False (kill switch for ablation),
    - the chat agent is unavailable (mock providers or missing key),
    - the LLM judges the question atomic (returns ``[]``),
    - or the agent call raises — any failure falls back to the empty list so the
      single_pass caller can fall through to the existing single-retrieve path.

    ``metadata`` carries ``agent_used`` plus a ``fallback_reason`` or ``error`` string so
    the trace records why decomposition did or did not run for this call. The list is
    truncated to ``settings.decomposition_max_subquestions``.
    """
    resolved = settings or get_settings()
    config = dataset_config or DatasetConfig.default_sec()
    metadata: dict[str, object] = {
        "agent_used": False,
        "model": resolved.zai_chat_model,
    }

    if not resolved.query_decomposition_enabled:
        metadata["fallback_reason"] = "decomposition_disabled"
        return [], metadata, TokenUsage()
    if not agent_available(resolved):
        metadata["fallback_reason"] = "agent_unavailable"
        return [], metadata, TokenUsage()

    try:
        agent = _build_decomposer_agent_for(resolved.zai_chat_model or "")
        result = agent.run_sync(f"QUESTION:\n{query}", deps=DecompDeps(dataset_config=config))
        usage = safe_pydantic_ai_usage(result, provider=Provider.ZAI, model=resolved.zai_chat_model)
        raw = result.output.subquestions if result.output is not None else []
        cleaned = [item.strip() for item in raw if item and item.strip()]
        if not cleaned:
            metadata["fallback_reason"] = "empty_subquestions"
            return [], metadata, usage
        limit = resolved.decomposition_max_subquestions
        truncated = cleaned[:limit]
        metadata["agent_used"] = True
        metadata["subquestion_count"] = len(truncated)
        if len(cleaned) > limit:
            metadata["truncated_from"] = len(cleaned)
        return truncated, metadata, usage
    except AGENT_RETRYABLE_ERRORS as exc:
        logger.warning("decomposition_failed", extra={"error": str(exc)})
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        return [], metadata, TokenUsage()
