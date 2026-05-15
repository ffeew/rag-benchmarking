from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from rag_common.config import Settings, get_settings
from rag_common.providers.openrouter import OpenRouterClient, ProviderError
from rag_common.usage import TokenUsage, from_openrouter_usage, merge, safe_pydantic_ai_usage

from rag_retrieval.agents import (
    agent_available,
    build_agent,
)
from rag_retrieval.verification import VerificationResult, keyword_verify_evidence

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from rag_retrieval.hybrid import RetrievedChunk
    from rag_retrieval.planning import RetrievalPlan


logger = logging.getLogger(__name__)


__all__ = [
    "AnswerDraft",
    "GeneratorOutput",
    "VerificationResult",
    "citation_label",
    "generate_answer",
    "generate_answer_with_agent",
    "keyword_verify_evidence",
    "local_grounded_answer",
    "snippet",
    "verify_evidence",
]


@dataclass(frozen=True)
class AnswerDraft:
    answer: str
    confidence: float
    insufficiency_reason: str | None
    metadata: dict[str, Any]


class GeneratorOutput(BaseModel):
    answer: str = Field(
        description=(
            "Final answer. Cite every material claim using the provided ##eN tags - "
            "for example: 'Revenue was $94B ##e1.'"
        ),
    )
    citations_used: list[str] = Field(
        default_factory=list,
        description="List of every ##eN tag actually referenced in the answer.",
    )
    insufficiency_reason: str | None = Field(
        default=None,
        description=("If evidence is insufficient, fill this with a short explanation; otherwise null."),
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence (0-1) in the answer given the evidence.",
    )


_GENERATOR_SYSTEM_PROMPT = """\
You are the answer writer for an SEC filings RAG system.

Strict rules:
- Answer ONLY from the provided evidence chunks. Do not use live market data.
- Cite every material claim using the ##eN tags exactly as supplied (e.g. ##e1, ##e2).
  A claim is "material" if it states a number, fact, or assertion from the filing.
- Each ##eN tag corresponds to one evidence chunk. NEVER invent a tag that was not in
  the evidence list. Re-use a tag multiple times if appropriate.
- If the evidence is insufficient, say so directly, set `insufficiency_reason`, and
  cite whatever partial evidence (if any) is relevant.
- For investment-recommendation questions, give an evidence-based comparison and call
  out limitations. Never give individualized advice.
- For "latest" or "current" questions, ground the answer in the most recent evidence
  filing date present and name that date.
- Keep the answer concise and operational - investor-style.

Output structure:
- `answer`: the prose answer with inline ##eN citations.
- `citations_used`: every ##eN tag referenced in `answer`, deduplicated.
- `insufficiency_reason`: null OR a short explanation if you could not answer.
- `confidence`: calibrated 0-1.
"""

_CITATION_TAG_RE = re.compile(r"##e(\d+)")


def citation_label(item: RetrievedChunk) -> str:
    filing = item.document.filing_date.isoformat() if item.document.filing_date else "undated"
    return f"[{item.document.ticker} {filing} {item.document.form_type}, p. {item.chunk.page_start}]"


def snippet(text: str, limit: int = 550) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."


def local_grounded_answer(
    question: str,  # noqa: ARG001
    evidence: list[RetrievedChunk],
    *,
    insufficiency_reason: str | None = None,
    generator: str = "local-extractive",
) -> AnswerDraft:
    if not evidence:
        return AnswerDraft(
            answer="The ingested dataset does not contain enough retrieved evidence to answer this question.",
            confidence=0.1,
            insufficiency_reason=insufficiency_reason or "No relevant evidence chunks were retrieved.",
            metadata={"generator": generator},
        )
    lines = ["Based on the ingested filings, the strongest retrieved evidence is:"]
    for item in evidence[:5]:
        lines.append(f"{citation_label(item)} {snippet(item.chunk.text, 320)}")
    return AnswerDraft(
        answer="\n".join(lines),
        confidence=min(0.9, 0.35 + len(evidence) * 0.08),
        insufficiency_reason=insufficiency_reason,
        metadata={"generator": generator},
    )


def verify_evidence(question: str, retrieved: list[RetrievedChunk]) -> VerificationResult:
    """Back-compat shim: returns only the VerificationResult, no metadata."""
    return keyword_verify_evidence(question, retrieved)


@lru_cache(maxsize=2)
def _build_generator_agent_for(model_id: str) -> Agent[None, GeneratorOutput]:  # noqa: ARG001
    return build_agent(
        output_type=GeneratorOutput,
        system_prompt=_GENERATOR_SYSTEM_PROMPT,
        name="sec-rag-generator",
    )


def _generator_agent(settings: Settings) -> Agent[None, GeneratorOutput]:
    return _build_generator_agent_for(settings.openrouter_chat_model or "")


def _build_evidence_context(evidence: list[RetrievedChunk]) -> tuple[str, dict[str, RetrievedChunk]]:
    blocks: list[str] = []
    tag_to_item: dict[str, RetrievedChunk] = {}
    for index, item in enumerate(evidence, start=1):
        tag = f"##e{index}"
        tag_to_item[tag] = item
        label = citation_label(item)
        blocks.append(f"{tag} {label} contains_table={item.chunk.contains_table}\n{item.chunk.text}")
    return "\n\n---\n\n".join(blocks), tag_to_item


def _extract_referenced_tags(answer: str, citations_used: list[str]) -> set[str]:
    tags: set[str] = set()
    for match in _CITATION_TAG_RE.finditer(answer):
        tags.add(f"##e{match.group(1)}")
    for entry in citations_used:
        stripped = entry.strip()
        if stripped.startswith("##e"):
            tags.add(stripped)
    return tags


def _validate_citations(
    output: GeneratorOutput,
    valid_tags: set[str],
) -> tuple[bool, set[str]]:
    referenced = _extract_referenced_tags(output.answer, output.citations_used)
    invalid = referenced - valid_tags
    return (not invalid), invalid


def _replace_tags_with_labels(answer: str, tag_to_item: dict[str, RetrievedChunk]) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = f"##e{match.group(1)}"
        item = tag_to_item.get(tag)
        if item is None:
            return tag
        return citation_label(item)

    return _CITATION_TAG_RE.sub(replace, answer)


def _build_generator_prompt(
    *,
    question: str,
    plan: RetrievalPlan | None,
    evidence_text: str,
    valid_tags: list[str],
) -> str:
    plan_block = ""
    if plan is not None and (plan.subquestions or plan.metrics or plan.query_type):
        parts: list[str] = []
        if plan.query_type:
            parts.append(f"query_type: {plan.query_type}")
        if plan.metrics:
            parts.append("metrics: " + ", ".join(plan.metrics))
        if plan.subquestions:
            parts.append("subquestions:\n- " + "\n- ".join(plan.subquestions))
        plan_block = "PLAN HINTS:\n" + "\n".join(parts) + "\n\n"
    return (
        f"{plan_block}"
        f"VALID CITATION TAGS: {', '.join(valid_tags)}\n\n"
        f"QUESTION:\n{question}\n\n"
        f"EVIDENCE:\n{evidence_text}"
    )


def _confidence_from_output(output: GeneratorOutput, fallback: float) -> float:
    if output.insufficiency_reason:
        return min(output.confidence, 0.4)
    return max(output.confidence, fallback)


def generate_answer_with_agent(
    *,
    question: str,
    evidence: list[RetrievedChunk],
    plan: RetrievalPlan | None,
    settings: Settings,
) -> tuple[AnswerDraft, TokenUsage]:
    if not evidence:
        return local_grounded_answer(question, []), TokenUsage()

    evidence_text, tag_to_item = _build_evidence_context(evidence)
    valid_tags = list(tag_to_item.keys())
    agent = _generator_agent(settings)

    prompt = _build_generator_prompt(
        question=question,
        plan=plan,
        evidence_text=evidence_text,
        valid_tags=valid_tags,
    )

    try:
        first = agent.run_sync(prompt)
    except Exception as exc:  # noqa: BLE001 - all failures fall back
        logger.warning("generator_first_pass_failed", extra={"error": str(exc)})
        return (
            local_grounded_answer(
                question,
                evidence,
                insufficiency_reason="Generator agent failed; using extractive fallback.",
                generator="local-extractive-after-agent-error",
            ),
            TokenUsage(),
        )

    accumulated_usage = safe_pydantic_ai_usage(first, provider="openrouter", model=settings.openrouter_chat_model)
    ok, invalid_tags = _validate_citations(first.output, set(valid_tags))
    citation_validation = "passed"
    repair_used = False
    final_output: GeneratorOutput = first.output

    if not ok:
        repair_used = True
        repair_prompt = (
            "Your previous answer cited tags that are not in the evidence list. "
            f"Invalid tags: {sorted(invalid_tags)}. "
            f"You MUST only use these valid tags: {valid_tags}. "
            "Re-emit the answer using only valid tags. If you cannot ground a claim, "
            "remove it or mark the response as insufficient.\n\n"
            "Previous answer (for reference):\n"
            f"{first.output.answer}\n\n"
            "Now answer the original question correctly:\n"
            f"{prompt}"
        )
        try:
            second = agent.run_sync(repair_prompt)
            accumulated_usage = merge(
                accumulated_usage,
                safe_pydantic_ai_usage(second, provider="openrouter", model=settings.openrouter_chat_model),
            )
            second_ok, _ = _validate_citations(second.output, set(valid_tags))
            if second_ok:
                citation_validation = "repaired"
                final_output = second.output
            else:
                citation_validation = "failed"
        except Exception as exc:  # noqa: BLE001
            logger.warning("generator_repair_failed", extra={"error": str(exc)})
            citation_validation = "failed"

    if citation_validation == "failed":
        return (
            local_grounded_answer(
                question,
                evidence,
                insufficiency_reason=("Generator citations could not be verified after one repair attempt."),
                generator="local-extractive-after-citation-repair-failed",
            ),
            accumulated_usage,
        )

    rendered = _replace_tags_with_labels(final_output.answer, tag_to_item)
    base_confidence = min(0.95, 0.45 + len(evidence) * 0.06)
    confidence = _confidence_from_output(final_output, base_confidence)
    metadata: dict[str, Any] = {
        "generator": "pydantic-ai-agent",
        "model": settings.openrouter_chat_model,
        "citation_validation": citation_validation,
        "repair_used": repair_used,
        "citations_used": final_output.citations_used,
        "evidence_tag_count": len(valid_tags),
    }
    return (
        AnswerDraft(
            answer=rendered,
            confidence=confidence,
            insufficiency_reason=final_output.insufficiency_reason,
            metadata=metadata,
        ),
        accumulated_usage,
    )


def _llm_only_answer(question: str, settings: Settings) -> tuple[AnswerDraft, TokenUsage]:
    provider = OpenRouterClient(settings)
    try:
        result = provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": "Answer without retrieved context for an ablation. State uncertainty clearly.",
                },
                {"role": "user", "content": question},
            ]
        )
        usage = from_openrouter_usage(
            result.metadata.usage,
            provider=result.metadata.provider,
            model=result.metadata.model,
        )
        return (
            AnswerDraft(
                answer=result.content,
                confidence=0.2,
                insufficiency_reason=None,
                metadata={
                    "generator": result.metadata.provider,
                    "model": result.metadata.model,
                    "ablation": "llm_only_no_retrieved_context",
                    "usage": result.metadata.usage,
                },
            ),
            usage,
        )
    except ProviderError:
        return (
            AnswerDraft(
                answer="LLM-only ablation could not be run because the chat provider is unavailable.",
                confidence=0.0,
                insufficiency_reason="Chat provider unavailable.",
                metadata={"generator": "provider-error"},
            ),
            TokenUsage(),
        )


def generate_answer(
    *,
    question: str,
    evidence: list[RetrievedChunk],
    retrieval_mode: str,
    plan: RetrievalPlan | None = None,
    settings: Settings | None = None,
) -> tuple[AnswerDraft, TokenUsage]:
    resolved = settings or get_settings()
    if retrieval_mode == "llm_only":
        return _llm_only_answer(question, resolved)

    if not evidence:
        return local_grounded_answer(question, []), TokenUsage()

    if not agent_available(resolved):
        return (
            local_grounded_answer(
                question,
                evidence,
                generator="local-extractive-mock-provider",
            ),
            TokenUsage(),
        )

    try:
        return generate_answer_with_agent(
            question=question,
            evidence=evidence,
            plan=plan,
            settings=resolved,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("generator_unexpected_error", extra={"error": str(exc)})
        return (
            local_grounded_answer(
                question,
                evidence,
                insufficiency_reason="Generator agent raised an unexpected error.",
                generator="local-extractive-after-unexpected-error",
            ),
            TokenUsage(),
        )
