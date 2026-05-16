from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext
from rag_common.config import Settings, get_settings
from rag_common.usage import TokenUsage, safe_pydantic_ai_usage

from rag_retrieval.agents import (
    agent_available,
    build_agent,
    run_with_fallback,
)
from rag_retrieval.dataset_config import DatasetConfig

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from rag_retrieval.hybrid import RetrievedChunk


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerificationResult:
    supported_chunk_ids: list[str]
    missing_subclaims: list[str]
    contradictions: list[str]
    retry_query: str | None
    confidence: float
    reasoning: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "supported_chunk_ids": self.supported_chunk_ids,
            "missing_subclaims": self.missing_subclaims,
            "contradictions": self.contradictions,
            "retry_query": self.retry_query,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


class VerifierOutput(BaseModel):
    supported_chunk_ids: list[str] = Field(
        default_factory=list,
        description="Subset of provided chunk_ids that materially support the question.",
    )
    missing_subclaims: list[str] = Field(
        default_factory=list,
        description="Sub-questions or claims that no retrieved chunk answers.",
    )
    contradictions: list[str] = Field(
        default_factory=list,
        description="Notable contradictions among the retrieved evidence.",
    )
    retry_query: str | None = Field(
        default=None,
        description=(
            "A rewritten retrieval query if recall failed; null if the current evidence "
            "is enough OR if retrying is unlikely to help."
        ),
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence (0-1) that the retained evidence can answer the question.",
    )
    reasoning: str = Field(
        default="",
        description="One or two sentences explaining the support/missing decisions.",
    )


STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "what",
        "was",
        "were",
        "how",
        "has",
        "their",
        "latest",
        "current",
        "reported",
        "give",
        "overview",
    }
)


_VERIFIER_INSTRUCTIONS = """\
You are the evidence verifier for a filings RAG system.

You will receive a user question and a numbered list of retrieved chunks (each with a
chunk_id, a human-readable label, and a snippet).

Your job:
1. Decide which chunk_ids genuinely contain evidence that answers (part of) the question.
   Be conservative: a chunk that merely mentions the topic or entity without addressing
   the question should NOT be in `supported_chunk_ids`.
2. List any missing subclaims - things the question asks for that the retrieved chunks
   do not cover.
3. Note any contradictions among the chunks.
4. If retrieval clearly missed relevant ground (low recall), propose `retry_query` with
   a different phrasing (broader or narrower as appropriate). Otherwise return null.
5. Output a calibrated confidence value (0.0 - 1.0). Use values <0.3 when nothing useful
   was retrieved, 0.5-0.7 for partial coverage, and >=0.8 only when every part of the
   question is firmly supported.

NEVER cite a chunk_id that was not in the provided list. Only return chunk_ids verbatim.
"""


def keywords(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9&-]{2,}", text) if word.lower() not in STOPWORDS}


def keyword_verify_evidence(question: str, retrieved: list[RetrievedChunk]) -> VerificationResult:
    question_terms = keywords(question)
    supported: list[str] = []
    for item in retrieved:
        overlap = question_terms & keywords(item.chunk.text)
        if overlap or item.semantic_rank is not None:
            supported.append(item.chunk.id)
    confidence = min(0.95, 0.25 + len(supported) * 0.1)
    missing: list[str] = []
    if not supported:
        missing.append("No retrieved chunk had enough lexical or semantic support for the question.")
    return VerificationResult(
        supported_chunk_ids=supported,
        missing_subclaims=missing,
        contradictions=[],
        retry_query=None if supported else " ".join(sorted(question_terms)),
        confidence=confidence if supported else 0.1,
        reasoning="keyword-overlap heuristic" if supported else "no keyword overlap with question terms",
    )


def _snippet(text: str, limit: int = 600) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."


def _evidence_label(item: RetrievedChunk, template: str | None = None) -> str:
    from rag_retrieval.dataset_config import DEFAULT_CITATION_LABEL_TEMPLATE, format_citation

    return format_citation(
        entity=item.document.ticker,
        filing_date=item.document.filing_date,
        form_type=item.document.form_type,
        page=item.chunk.page_start,
        template=template or DEFAULT_CITATION_LABEL_TEMPLATE,
    )


def _build_verifier_prompt(question: str, retrieved: list[RetrievedChunk]) -> str:
    lines: list[str] = [f"QUESTION:\n{question}", "", "EVIDENCE:"]
    for index, item in enumerate(retrieved, start=1):
        lines.append(
            f"{index}. chunk_id={item.chunk.id} {_evidence_label(item)} "
            f"contains_table={item.chunk.contains_table}\n   {_snippet(item.chunk.text)}"
        )
    if not retrieved:
        lines.append("(no chunks retrieved)")
    return "\n".join(lines)


@dataclass(frozen=True)
class VerifierDeps:
    """Per-run context for the verifier.

    ``valid_chunk_ids`` enables an ``@agent.output_validator`` to reject (and trigger
    a single ModelRetry on) any ``supported_chunk_ids`` entry that was not in the
    provided evidence list - the docs flag this exact pattern as the canonical
    alternative to silent post-run filtering. ``dataset_config`` lets dynamic
    instructions name the corpus the verifier is judging against.
    """

    valid_chunk_ids: frozenset[str]
    dataset_config: DatasetConfig


@lru_cache(maxsize=2)
def _build_verifier_agent_for(model_id: str) -> Agent[VerifierDeps, VerifierOutput]:  # noqa: ARG001
    agent: Agent[VerifierDeps, VerifierOutput] = build_agent(
        deps_type=VerifierDeps,
        output_type=VerifierOutput,
        instructions=_VERIFIER_INSTRUCTIONS,
        name="rag-verifier",
        output_retries=1,
    )

    @agent.instructions
    def verifier_context(ctx: RunContext[VerifierDeps]) -> str:
        return f"CORPUS: {ctx.deps.dataset_config.domain_label}"

    @agent.output_validator
    def validate_supported_ids(
        ctx: RunContext[VerifierDeps],
        output: VerifierOutput,
    ) -> VerifierOutput:
        valid = ctx.deps.valid_chunk_ids
        invalid = [chunk_id for chunk_id in output.supported_chunk_ids if chunk_id not in valid]
        if invalid:
            raise ModelRetry(
                f"supported_chunk_ids contains ids not present in the evidence list: {invalid}. "
                "Cite only chunk_ids that appear in the EVIDENCE block, verbatim."
            )
        return output

    return agent


def _verifier_agent(settings: Settings) -> Agent[VerifierDeps, VerifierOutput]:
    return _build_verifier_agent_for(settings.zai_chat_model or "")


def _normalize_verifier_output(
    output: VerifierOutput,
    retrieved: list[RetrievedChunk],
) -> VerificationResult:
    valid_ids = {item.chunk.id for item in retrieved}
    supported = [chunk_id for chunk_id in output.supported_chunk_ids if chunk_id in valid_ids]
    retry_query = output.retry_query.strip() if output.retry_query else None
    if retry_query == "":
        retry_query = None
    return VerificationResult(
        supported_chunk_ids=supported,
        missing_subclaims=[claim.strip() for claim in output.missing_subclaims if claim.strip()],
        contradictions=[item.strip() for item in output.contradictions if item.strip()],
        retry_query=retry_query,
        confidence=float(output.confidence),
        reasoning=output.reasoning or None,
    )


def verify_evidence(
    question: str,
    retrieved: list[RetrievedChunk],
    settings: Settings | None = None,
    *,
    dataset_config: DatasetConfig | None = None,
) -> tuple[VerificationResult, dict[str, Any], TokenUsage]:
    resolved = settings or get_settings()
    config = dataset_config or DatasetConfig.default_sec()
    metadata: dict[str, Any] = {"agent_used": False, "model": None, "error": None}

    if not agent_available(resolved) or not retrieved:
        result = keyword_verify_evidence(question, retrieved)
        metadata["model"] = resolved.zai_chat_model
        metadata["fallback_reason"] = "no_retrieved_evidence" if not retrieved else "agent_unavailable"
        return result, metadata, TokenUsage()

    deps = VerifierDeps(
        valid_chunk_ids=frozenset(item.chunk.id for item in retrieved),
        dataset_config=config,
    )

    def run_agent() -> tuple[VerificationResult, TokenUsage]:
        agent = _verifier_agent(resolved)
        result = agent.run_sync(_build_verifier_prompt(question, retrieved), deps=deps)
        usage = safe_pydantic_ai_usage(
            result,
            provider="zai",
            model=resolved.zai_chat_model,
        )
        return _normalize_verifier_output(result.output, retrieved), usage

    def fallback() -> VerificationResult:
        return keyword_verify_evidence(question, retrieved)

    result, used_agent, error, usage = run_with_fallback(run_agent, fallback, label="verifier")
    metadata["agent_used"] = used_agent
    metadata["model"] = resolved.zai_chat_model
    metadata["error"] = error
    return result, metadata, usage
