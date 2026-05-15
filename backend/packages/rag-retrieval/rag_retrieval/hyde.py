"""HyDE (Hypothetical Document Embeddings) passage generator.

HyDE (Gao et al., 2022) asks an LLM to draft a hypothetical answer-shaped passage for a
question, then embeds that passage for vector search. For SEC filings the formal
accounting register of a plausible 10-K/10-Q excerpt is closer in embedding space to
actual filing chunks than the literal investor question, which improves recall on vague
or qualitative queries while still letting BM25/FTS pin to the user's exact wording.
"""

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from rag_common.config import Settings, get_settings
from rag_common.usage import TokenUsage, safe_pydantic_ai_usage

from rag_retrieval.agents import agent_available, build_agent

if TYPE_CHECKING:
    from pydantic_ai import Agent

logger = logging.getLogger(__name__)


_HYDE_SYSTEM_PROMPT = """\
You generate hypothetical SEC filing excerpts for retrieval-only purposes.

Given a question about a public company's 10-K, 10-Q, or 8-K filing, write a short
(3-5 sentence) passage in the formal style of an SEC filing that WOULD answer the
question. The passage will be embedded for vector search; factual accuracy is NOT
required - plausibility of wording, structure, and accounting terminology is.

Use the register of management's discussion and analysis (MD&A), notes to financial
statements, or risk factors - whichever matches the question type. Include concrete
numbers, dates, and segment names when the question implies them. Stay under 100 words.

Output the passage text only - no header, no label, no quotation marks.
"""


@lru_cache(maxsize=2)
def _build_hyde_agent_for(model_id: str) -> "Agent[None, str]":  # noqa: ARG001 - model_id keys the cache
    return build_agent(
        output_type=str,
        system_prompt=_HYDE_SYSTEM_PROMPT,
        name="sec-rag-hyde",
    )


def generate_hyde_passage(
    query: str,
    settings: Settings | None = None,
) -> tuple[str, dict[str, object], TokenUsage]:
    """Generate a hypothetical SEC filing passage for HyDE-based retrieval.

    Returns ``(passage, metadata, usage)``. The passage is the original ``query`` when:

    - ``settings.hyde_enabled`` is False (kill switch for ablation),
    - the chat agent is unavailable (mock providers or missing key),
    - or the agent call raises - any failure falls back to the bare query so retrieval
      still proceeds.

    ``metadata`` carries ``agent_used`` plus a ``fallback_reason`` or ``error`` string so
    the trace records why HyDE did or did not run for this call.
    """
    resolved = settings or get_settings()
    metadata: dict[str, object] = {
        "agent_used": False,
        "model": resolved.openrouter_chat_model,
    }

    if not resolved.hyde_enabled:
        metadata["fallback_reason"] = "hyde_disabled"
        return query, metadata, TokenUsage()
    if not agent_available(resolved):
        metadata["fallback_reason"] = "agent_unavailable"
        return query, metadata, TokenUsage()

    try:
        agent = _build_hyde_agent_for(resolved.openrouter_chat_model or "")
        result = agent.run_sync(f"QUESTION:\n{query}")
        usage = safe_pydantic_ai_usage(result, provider="openrouter", model=resolved.openrouter_chat_model)
        passage = (result.output or "").strip()
        if not passage:
            metadata["fallback_reason"] = "empty_passage"
            return query, metadata, usage
        metadata["agent_used"] = True
        return passage, metadata, usage
    except Exception as exc:  # noqa: BLE001 - HyDE failure must never block retrieval
        logger.warning("hyde_failed", extra={"error": str(exc)})
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        return query, metadata, TokenUsage()
