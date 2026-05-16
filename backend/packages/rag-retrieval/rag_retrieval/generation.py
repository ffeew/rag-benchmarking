import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from rag_common.config import Settings, get_settings
from rag_common.enums import Provider, RetrievalMode
from rag_common.providers.openrouter import ProviderError
from rag_common.providers.zai import ZaiClient
from rag_common.usage import TokenUsage, from_openrouter_usage, safe_pydantic_ai_usage

from rag_retrieval.agents import (
    AGENT_RETRYABLE_ERRORS,
    agent_available,
    build_agent,
)
from rag_retrieval.dataset_config import (
    DEFAULT_CITATION_LABEL_TEMPLATE,
    DatasetConfig,
    format_citation,
)
from rag_retrieval.hybrid import RetrievedChunk
from rag_retrieval.planning import RetrievalPlan
from rag_retrieval.verification import VerificationResult, keyword_verify_evidence

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


_GENERATOR_INSTRUCTIONS = """\
You are the answer writer for a filings RAG system.

Strict rules:
- Answer ONLY from the provided evidence chunks. Do not use live or external data.
- Cite every material claim using the ##eN tags exactly as supplied (e.g. ##e1, ##e2).
  A claim is "material" if it states a number, fact, or assertion from the corpus.
- Each ##eN tag corresponds to one evidence chunk. NEVER invent a tag that was not in
  the evidence list. Re-use a tag multiple times if appropriate.
- If the evidence is insufficient, say so directly, set `insufficiency_reason`, and
  cite whatever partial evidence (if any) is relevant.
- For questions seeking advice or recommendations, give an evidence-based comparison
  and call out limitations. Never give individualized advice.
- For "latest" or "current" questions, ground the answer in the most recent evidence
  filing date present and name that date.
- Keep the answer concise and operational.

Output structure:
- `answer`: the prose answer with inline ##eN citations.
- `citations_used`: every ##eN tag referenced in `answer`, deduplicated.
- `insufficiency_reason`: null OR a short explanation if you could not answer.
- `confidence`: calibrated 0-1.
"""

_CITATION_TAG_RE = re.compile(r"##e(\d+)")


def citation_label(item: RetrievedChunk, template: str | None = None) -> str:
    """Render a citation label for a retrieved chunk.

    ``template`` is the dataset's ``citation_label_template`` (``DatasetConfig``); when
    None, falls back to the SEC-shaped default ``[TICKER YYYY-MM-DD FORM, p. N]``.
    """
    return format_citation(
        entity=item.document.ticker,
        filing_date=item.document.filing_date,
        form_type=item.document.form_type,
        page=item.chunk.page_start,
        template=template or DEFAULT_CITATION_LABEL_TEMPLATE,
    )


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
    citation_template: str | None = None,
) -> AnswerDraft:
    if not evidence:
        return AnswerDraft(
            answer="The ingested dataset does not contain enough retrieved evidence to answer this question.",
            confidence=0.1,
            insufficiency_reason=insufficiency_reason or "No relevant evidence chunks were retrieved.",
            metadata={"generator": generator},
        )
    lines = ["Based on the ingested corpus, the strongest retrieved evidence is:"]
    for item in evidence[:5]:
        lines.append(f"{citation_label(item, citation_template)} {snippet(item.chunk.text, 320)}")
    # Cap fallback confidence at 0.4 so callers can distinguish extractive-fallback
    # answers from calibrated agent answers. The previous 0.75-for-5-chunks heuristic
    # was indistinguishable from a real generator output.
    return AnswerDraft(
        answer="\n".join(lines),
        confidence=min(0.4, 0.1 + len(evidence) * 0.05),
        insufficiency_reason=insufficiency_reason,
        metadata={"generator": generator},
    )


def verify_evidence(question: str, retrieved: list[RetrievedChunk]) -> VerificationResult:
    """Back-compat shim: returns only the VerificationResult, no metadata."""
    return keyword_verify_evidence(question, retrieved)


@dataclass(frozen=True)
class GeneratorDeps:
    """Per-run context for the generator.

    ``valid_tags`` enables an ``@agent.output_validator`` to raise ``ModelRetry`` when
    the model fabricates a citation tag - the documented pydantic-ai replacement for
    the hand-rolled "build a repair prompt and call the agent a second time" pattern.
    ``dataset_config`` lets dynamic instructions name the corpus the answer is being
    written against.
    """

    valid_tags: frozenset[str]
    dataset_config: DatasetConfig


@lru_cache(maxsize=2)
def _build_generator_agent_for(model_id: str) -> Agent[GeneratorDeps, GeneratorOutput]:  # noqa: ARG001
    agent: Agent[GeneratorDeps, GeneratorOutput] = build_agent(
        deps_type=GeneratorDeps,
        output_type=GeneratorOutput,
        instructions=_GENERATOR_INSTRUCTIONS,
        name="rag-generator",
        output_retries=2,
    )

    @agent.instructions
    def generator_context(ctx: RunContext[GeneratorDeps]) -> str:
        return f"CORPUS: {ctx.deps.dataset_config.domain_label}"

    @agent.output_validator
    def validate_citations(
        ctx: RunContext[GeneratorDeps],
        output: GeneratorOutput,
    ) -> GeneratorOutput:
        valid = ctx.deps.valid_tags
        referenced = _extract_referenced_tags(output.answer, output.citations_used)
        invalid = referenced - valid
        if invalid:
            raise ModelRetry(
                f"Invalid citation tags: {sorted(invalid)}. "
                f"Use only: {sorted(valid)}. "
                "Re-emit the answer using only valid tags; if you cannot ground a claim, "
                "remove it or set insufficiency_reason."
            )
        return output

    return agent


def _generator_agent(settings: Settings) -> Agent[GeneratorDeps, GeneratorOutput]:
    return _build_generator_agent_for(settings.zai_chat_model or "")


def _build_evidence_context(
    evidence: list[RetrievedChunk],
    citation_template: str | None = None,
) -> tuple[str, dict[str, RetrievedChunk]]:
    blocks: list[str] = []
    tag_to_item: dict[str, RetrievedChunk] = {}
    for index, item in enumerate(evidence, start=1):
        tag = f"##e{index}"
        tag_to_item[tag] = item
        label = citation_label(item, citation_template)
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


def _replace_tags_with_labels(
    answer: str,
    tag_to_item: dict[str, RetrievedChunk],
    citation_template: str | None = None,
) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = f"##e{match.group(1)}"
        item = tag_to_item.get(tag)
        if item is None:
            return tag
        return citation_label(item, citation_template)

    return _CITATION_TAG_RE.sub(replace, answer)


def _build_generator_prompt(
    *,
    question: str,
    plan: RetrievalPlan | None,
    evidence_text: str,
    valid_tags: list[str],
    missing_subclaims: list[str] | None = None,
    contradictions: list[str] | None = None,
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
    verifier_block = ""
    flags: list[str] = []
    if missing_subclaims:
        flags.append("missing_subclaims:\n- " + "\n- ".join(missing_subclaims))
    if contradictions:
        flags.append("contradictions:\n- " + "\n- ".join(contradictions))
    if flags:
        verifier_block = (
            "VERIFIER FLAGS (hedge or call these out explicitly in the answer):\n" + "\n".join(flags) + "\n\n"
        )
    return (
        f"{plan_block}"
        f"{verifier_block}"
        f"VALID CITATION TAGS: {', '.join(valid_tags)}\n\n"
        f"QUESTION:\n{question}\n\n"
        f"EVIDENCE:\n{evidence_text}"
    )


def _confidence_from_output(output: GeneratorOutput, fallback: float) -> float:
    if output.insufficiency_reason:
        return min(output.confidence, 0.4)
    return max(output.confidence, fallback)


def _request_count(result: object) -> int:
    """Read ``usage.requests`` from a pydantic-ai run result; default to 1 on absence."""
    usage_value = getattr(result, "usage", None)
    if usage_value is None:
        return 1
    return int(getattr(usage_value, "requests", 1) or 1)


def generate_answer_with_agent(
    *,
    question: str,
    evidence: list[RetrievedChunk],
    plan: RetrievalPlan | None,
    settings: Settings,
    missing_subclaims: list[str] | None = None,
    contradictions: list[str] | None = None,
    dataset_config: DatasetConfig | None = None,
) -> tuple[AnswerDraft, TokenUsage]:
    config = dataset_config or DatasetConfig.default_sec()
    template = config.citation_label_template
    if not evidence:
        return local_grounded_answer(question, [], citation_template=template), TokenUsage()

    evidence_text, tag_to_item = _build_evidence_context(evidence, template)
    valid_tags = list(tag_to_item.keys())
    deps = GeneratorDeps(valid_tags=frozenset(valid_tags), dataset_config=config)
    agent = _generator_agent(settings)

    prompt = _build_generator_prompt(
        question=question,
        plan=plan,
        evidence_text=evidence_text,
        valid_tags=valid_tags,
        missing_subclaims=missing_subclaims,
        contradictions=contradictions,
    )

    # The citation validator (registered on the agent) raises ModelRetry when the model
    # invents a tag - pydantic-ai performs one bounded repair turn automatically and only
    # raises UnexpectedModelBehavior if the retry budget (output_retries=1) is exhausted.
    try:
        result = agent.run_sync(prompt, deps=deps)
    except AGENT_RETRYABLE_ERRORS as exc:
        logger.warning("generator_failed", extra={"error": str(exc)})
        # An UnexpectedModelBehavior here usually means citation_validator never converged.
        return (
            local_grounded_answer(
                question,
                evidence,
                insufficiency_reason="Generator agent failed or could not produce valid citations.",
                generator="local-extractive-after-agent-error",
                citation_template=template,
            ),
            TokenUsage(),
        )

    accumulated_usage = safe_pydantic_ai_usage(result, provider=Provider.ZAI, model=settings.zai_chat_model)
    repair_used = _request_count(result) > 1
    final_output: GeneratorOutput = result.output

    rendered = _replace_tags_with_labels(final_output.answer, tag_to_item, template)
    base_confidence = min(0.95, 0.45 + len(evidence) * 0.06)
    confidence = _confidence_from_output(final_output, base_confidence)
    metadata: dict[str, Any] = {
        "generator": "pydantic-ai-agent",
        "model": settings.zai_chat_model,
        "citation_validation": "repaired" if repair_used else "passed",
        "repair_used": repair_used,
        "citations_used": final_output.citations_used,
        "evidence_tag_count": len(valid_tags),
        "citation_label_template": template,
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
    provider = ZaiClient(settings)
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
    missing_subclaims: list[str] | None = None,
    contradictions: list[str] | None = None,
    dataset_config: DatasetConfig | None = None,
) -> tuple[AnswerDraft, TokenUsage]:
    resolved = settings or get_settings()
    config = dataset_config or DatasetConfig.default_sec()
    template = config.citation_label_template
    if retrieval_mode == RetrievalMode.LLM_ONLY:
        return _llm_only_answer(question, resolved)

    if not evidence:
        return local_grounded_answer(question, [], citation_template=template), TokenUsage()

    if not agent_available(resolved):
        return (
            local_grounded_answer(
                question,
                evidence,
                generator="local-extractive-mock-provider",
                citation_template=template,
            ),
            TokenUsage(),
        )

    try:
        return generate_answer_with_agent(
            question=question,
            evidence=evidence,
            plan=plan,
            settings=resolved,
            missing_subclaims=missing_subclaims,
            contradictions=contradictions,
            dataset_config=config,
        )
    except AGENT_RETRYABLE_ERRORS as exc:
        logger.warning("generator_unexpected_error", extra={"error": str(exc)})
        return (
            local_grounded_answer(
                question,
                evidence,
                insufficiency_reason="Generator agent raised an unexpected error.",
                generator="local-extractive-after-unexpected-error",
                citation_template=template,
            ),
            TokenUsage(),
        )
