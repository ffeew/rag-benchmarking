"""HyDE (Hypothetical Document Embeddings) passage generator.

HyDE (Gao et al., 2022) asks an LLM to draft a hypothetical answer-shaped passage for
a question, then embeds that passage for vector search. The corpus-style hint comes
from the dataset config so the same prompt works for any registered dataset; on the
default SEC corpus the resulting passages still match filing tone via the runtime
``CORPUS:`` and ``STYLE_HINT:`` lines.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

from pydantic_ai import (
    Agent,
    RunContext,  # noqa: TC002 - resolved at runtime by @agent.instructions via get_type_hints
)
from rag_common.config import Settings, get_settings
from rag_common.usage import TokenUsage, safe_pydantic_ai_usage

from rag_retrieval.agents import AGENT_RETRYABLE_ERRORS, agent_available, build_agent
from rag_retrieval.dataset_config import DatasetConfig

logger = logging.getLogger(__name__)


_HYDE_INSTRUCTIONS = """\
You generate hypothetical document excerpts for retrieval-only purposes.

Given a question about the ingested corpus, write a short (3-5 sentence) passage in the
formal disclosure register of that corpus that WOULD answer the question. The passage
will be embedded for vector search; factual accuracy is NOT required - plausibility of
wording, structure, and domain terminology is.

Match the register the question implies: narrative discussion, tabular numeric data,
or risk / uncertainty language as appropriate. Include concrete numbers, dates, and
named entities (e.g. companies, products, segments) when the question implies them.
Stay under 100 words.

Output the passage text only - no header, no label, no quotation marks.
"""


@dataclass(frozen=True)
class HydeDeps:
    """Per-call context for the HyDE agent.

    Carries the resolved dataset config so dynamic instructions can name the corpus
    and append a dataset-specific style hint without rebuilding the agent per call.
    """

    dataset_config: DatasetConfig


@lru_cache(maxsize=2)
def _build_hyde_agent_for(model_id: str) -> Agent[HydeDeps, str]:  # noqa: ARG001 - model_id keys the cache
    agent: Agent[HydeDeps, str] = build_agent(
        deps_type=HydeDeps,
        output_type=str,
        instructions=_HYDE_INSTRUCTIONS,
        name="rag-hyde",
    )

    @agent.instructions
    def hyde_context(ctx: RunContext[HydeDeps]) -> str:
        config = ctx.deps.dataset_config
        lines = [f"CORPUS: {config.domain_label}"]
        if config.hyde_style_hint:
            lines.append(f"STYLE_HINT: {config.hyde_style_hint}")
        return "\n".join(lines)

    return agent


def generate_hyde_passage(
    query: str,
    settings: Settings | None = None,
    *,
    dataset_config: DatasetConfig | None = None,
) -> tuple[str, dict[str, object], TokenUsage]:
    """Generate a hypothetical document passage for HyDE-based retrieval.

    Returns ``(passage, metadata, usage)``. The passage is the original ``query`` when:

    - ``settings.hyde_enabled`` is False (kill switch for ablation),
    - the chat agent is unavailable (mock providers or missing key),
    - or the agent call raises - any failure falls back to the bare query so retrieval
      still proceeds.

    ``metadata`` carries ``agent_used`` plus a ``fallback_reason`` or ``error`` string so
    the trace records why HyDE did or did not run for this call. ``dataset_config``
    defaults to the SEC defaults so callers that have not yet been wired through can
    drop in without breaking.
    """
    resolved = settings or get_settings()
    config = dataset_config or DatasetConfig.default_sec()
    metadata: dict[str, object] = {
        "agent_used": False,
        "model": resolved.zai_chat_model,
    }

    if not resolved.hyde_enabled:
        metadata["fallback_reason"] = "hyde_disabled"
        return query, metadata, TokenUsage()
    if not agent_available(resolved):
        metadata["fallback_reason"] = "agent_unavailable"
        return query, metadata, TokenUsage()

    try:
        agent = _build_hyde_agent_for(resolved.zai_chat_model or "")
        result = agent.run_sync(f"QUESTION:\n{query}", deps=HydeDeps(dataset_config=config))
        usage = safe_pydantic_ai_usage(result, provider="zai", model=resolved.zai_chat_model)
        passage = (result.output or "").strip()
        if not passage:
            metadata["fallback_reason"] = "empty_passage"
            return query, metadata, usage
        metadata["agent_used"] = True
        return passage, metadata, usage
    except AGENT_RETRYABLE_ERRORS as exc:
        logger.warning("hyde_failed", extra={"error": str(exc)})
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        return query, metadata, TokenUsage()
