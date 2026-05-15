"""Retriever, citation, and answer metrics for the SEC-filings RAG benchmark.

All functions are pure and side-effect-free. They consume typed input models built from
the evaluation runner's saved data — never SQLAlchemy ORM objects directly — so they can
be unit-tested without a database.
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field


class ExpectedCitation(BaseModel):
    """Expected-citation hint stored per eval case."""

    ticker: str | None = None
    form_type: str | None = None
    page_number: int | None = None
    document_id: str | None = None
    evidence_text: str | None = None


class RetrievedChunkRef(BaseModel):
    """Lightweight reference to a retrieved chunk for retriever-quality scoring."""

    chunk_id: str
    document_id: str
    ticker: str
    form_type: str
    page_start: int
    page_end: int
    rank: int


class ChunkSnapshot(BaseModel):
    """Slice of a chunk used to verify citation evidence text."""

    chunk_id: str
    document_id: str
    text: str
    page_start: int
    page_end: int


class CitationSnapshot(BaseModel):
    """Citation produced by the answer pipeline, used for validity scoring."""

    chunk_id: str
    document_id: str
    page_number: int
    evidence_text: str


class PlanFilters(BaseModel):
    """Filters the planner applied. Empty lists mean no restriction at that dimension."""

    target_tickers: list[str] = Field(default_factory=list)
    forms: list[str] = Field(default_factory=list)
    filing_date_start: date | None = None
    filing_date_end: date | None = None

    @classmethod
    def from_plan_dict(cls, plan: dict[str, object]) -> PlanFilters:
        target_tickers = _coerce_str_list(plan.get("target_tickers"))
        forms = _coerce_str_list(plan.get("forms"))
        return cls(
            target_tickers=[ticker.upper() for ticker in target_tickers],
            forms=[form.upper() for form in forms],
            filing_date_start=_coerce_date(plan.get("filing_date_start")),
            filing_date_end=_coerce_date(plan.get("filing_date_end")),
        )


# ---------- retriever metrics ----------

def recall_at_k(expected: list[ExpectedCitation], retrieved: list[RetrievedChunkRef], k: int) -> float:
    """Fraction of expected citations covered by the top-k retrieval.

    Matches by document_id when present, otherwise by (ticker, form_type, page_number).
    Returns 0.0 when there are no expected citations (nothing to recall).
    """
    if not expected or k <= 0:
        return 0.0
    top_k = retrieved[:k]
    matched_indices: set[int] = set()
    for index, exp in enumerate(expected):
        if _matches_any(exp, top_k):
            matched_indices.add(index)
    return len(matched_indices) / len(expected)


def mean_reciprocal_rank(expected: list[ExpectedCitation], retrieved: list[RetrievedChunkRef]) -> float:
    """1/rank of the first retrieved chunk that matches ANY expected citation. 0.0 if none match."""
    if not expected or not retrieved:
        return 0.0
    for item in retrieved:
        for exp in expected:
            if _single_match(exp, item):
                return 1.0 / max(item.rank, 1)
    return 0.0


def page_evidence_f1(
    expected_pages: set[tuple[str, int]],
    retrieved_pages: set[tuple[str, int]],
) -> float:
    """F1 over the set of (document_id, page_number) pairs.

    Returns 1.0 when both sets are empty (vacuous truth). Returns 0.0 when one is empty.
    """
    if not expected_pages and not retrieved_pages:
        return 1.0
    if not expected_pages or not retrieved_pages:
        return 0.0
    true_positives = len(expected_pages & retrieved_pages)
    if true_positives == 0:
        return 0.0
    precision = true_positives / len(retrieved_pages)
    recall = true_positives / len(expected_pages)
    return 2 * precision * recall / (precision + recall)


def metadata_filter_correctness(plan_filters: PlanFilters, expected: list[ExpectedCitation]) -> float:
    """1.0 iff the planner's filters do not exclude any expected citation. 0.0 otherwise.

    A filter excludes an expected citation when:
      - target_tickers is non-empty AND the expected ticker is set AND not in target_tickers; or
      - forms is non-empty AND the expected form is set AND not in forms.

    Returns 1.0 when expected is empty (no filter to test against).
    """
    if not expected:
        return 1.0
    target_tickers = {ticker.upper() for ticker in plan_filters.target_tickers}
    forms = {form.upper() for form in plan_filters.forms}
    for exp in expected:
        if target_tickers and exp.ticker and exp.ticker.upper() not in target_tickers:
            return 0.0
        if forms and exp.form_type and exp.form_type.upper() not in forms:
            return 0.0
    return 1.0


# ---------- citation metrics ----------

def citation_validity(
    citations: list[CitationSnapshot],
    chunks_by_id: dict[str, ChunkSnapshot],
) -> float:
    """Fraction of citations whose chunk_id resolves AND whose evidence text grounds in the chunk.

    Evidence text is "grounded" if a whitespace-normalized prefix of the citation's
    evidence_text (first 80 chars) appears in the chunk's normalized text. We use a prefix
    rather than the full snippet because chunkers may truncate, and the goal is to detect
    fabricated citations, not to grade prose similarity.

    Returns 0.0 when there are no citations.
    """
    if not citations:
        return 0.0
    valid = 0
    for citation in citations:
        chunk = chunks_by_id.get(citation.chunk_id)
        if chunk is None:
            continue
        if _evidence_grounded(citation.evidence_text, chunk.text):
            valid += 1
    return valid / len(citations)


_CITATION_TAG_RE = re.compile(r"##e(\d+)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_MATERIAL_CLAIM_RE = re.compile(r"[\d,]+(?:\.\d+)?\s*(?:%|million|billion|trillion|basis\s+points|bps|\$)", re.IGNORECASE)


def citation_coverage(answer: str, citations_used: list[str]) -> float:
    """Fraction of material claim sentences that contain at least one ##eN tag.

    A sentence is "material" if it contains a number, percentage, dollar amount, or
    quantitative phrase per ``_MATERIAL_CLAIM_RE``. Returns 1.0 when there are no
    material claims (nothing to cite) or when ``citations_used`` is provided as a
    fallback signal that the generator referenced citations at all.
    """
    sentences = [sentence.strip() for sentence in _SENTENCE_SPLIT_RE.split(answer.strip()) if sentence.strip()]
    if not sentences:
        return 1.0
    material_sentences = [sentence for sentence in sentences if _is_material_claim(sentence)]
    if not material_sentences:
        return 1.0
    cited = sum(1 for sentence in material_sentences if _CITATION_TAG_RE.search(sentence))
    if cited == 0 and citations_used:
        # Generator used citations but rendering replaced ##eN tags with labels. Treat as half-coverage.
        return 0.5
    return cited / len(material_sentences)


# ---------- helpers ----------

def _matches_any(expected: ExpectedCitation, retrieved: list[RetrievedChunkRef]) -> bool:
    return any(_single_match(expected, item) for item in retrieved)


def _single_match(expected: ExpectedCitation, item: RetrievedChunkRef) -> bool:
    if expected.document_id and expected.document_id == item.document_id:
        if expected.page_number is None:
            return True
        return item.page_start <= expected.page_number <= item.page_end
    if expected.ticker and expected.ticker.upper() != item.ticker.upper():
        return False
    if expected.form_type and expected.form_type.upper() != item.form_type.upper():
        return False
    if expected.page_number is not None:
        return item.page_start <= expected.page_number <= item.page_end
    return bool(expected.ticker)


def _evidence_grounded(evidence_text: str, chunk_text: str) -> bool:
    if not evidence_text or not chunk_text:
        return False
    needle = _normalize_whitespace(evidence_text)[:80]
    haystack = _normalize_whitespace(chunk_text)
    return needle in haystack


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_material_claim(sentence: str) -> bool:
    if _MATERIAL_CLAIM_RE.search(sentence):
        return True
    return "$" in sentence or any(char.isdigit() for char in sentence)


def _coerce_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _coerce_date(value: object) -> date | None:
    if value is None or not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
