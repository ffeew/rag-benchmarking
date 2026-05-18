import re
from dataclasses import dataclass
from typing import Any

from rag_retrieval.hybrid import RetrievedChunk


@dataclass(frozen=True)
class VerificationResult:
    supported_chunk_ids: list[str]
    missing_subclaims: list[str]
    contradictions: list[str]
    confidence: float
    reasoning: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "supported_chunk_ids": self.supported_chunk_ids,
            "missing_subclaims": self.missing_subclaims,
            "contradictions": self.contradictions,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


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


def keywords(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9&-]{2,}", text) if word.lower() not in STOPWORDS}


def keyword_verify_evidence(question: str, retrieved: list[RetrievedChunk]) -> VerificationResult:
    question_terms = keywords(question)
    supported: list[str] = []
    for item in retrieved:
        overlap = question_terms & keywords(item.chunk.text)
        if overlap or item.semantic_rank is not None:
            supported.append(item.chunk.id)
    # Cap heuristic verifier confidence at 0.5 so callers can distinguish keyword-based
    # support from LLM-calibrated support. Previously this returned 0.95 for ≥7 chunks
    # with any lexical overlap — indistinguishable from real verifier output.
    confidence = min(0.5, 0.1 + len(supported) * 0.05)
    missing: list[str] = []
    if not supported:
        missing.append("No retrieved chunk had enough lexical or semantic support for the question.")
    return VerificationResult(
        supported_chunk_ids=supported,
        missing_subclaims=missing,
        contradictions=[],
        confidence=confidence if supported else 0.1,
        reasoning="keyword-overlap heuristic" if supported else "no keyword overlap with question terms",
    )
