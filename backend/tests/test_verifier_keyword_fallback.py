from types import SimpleNamespace
from typing import cast

from rag_benchmarking.retrieval.hybrid import RetrievedChunk
from rag_benchmarking.retrieval.verification import keyword_verify_evidence


def _chunk(chunk_id: str, text: str, *, semantic_rank: int | None = None) -> RetrievedChunk:
    return cast(
        "RetrievedChunk",
        SimpleNamespace(
            chunk=SimpleNamespace(id=chunk_id, text=text),
            document=None,
            score=0.5,
            semantic_rank=semantic_rank,
            lexical_rank=None,
            rerank_score=None,
        ),
    )


def test_keyword_verify_finds_overlap_with_question() -> None:
    chunks = [
        _chunk("c1", "Apple total revenue reached $394 billion in fiscal 2024.", semantic_rank=1),
        _chunk("c2", "Quantum entanglement was demonstrated in 1982.", semantic_rank=None),
    ]
    result = keyword_verify_evidence("What was Apple's revenue?", chunks)

    assert "c1" in result.supported_chunk_ids
    assert result.confidence > 0.1


def test_keyword_verify_returns_low_confidence_when_nothing_matches() -> None:
    chunks = [
        _chunk("c1", "Quantum entanglement was demonstrated in 1982."),
    ]
    result = keyword_verify_evidence("Microsoft Azure pricing in Asia", chunks)

    assert result.supported_chunk_ids == []
    assert result.retry_query is not None
    assert result.confidence <= 0.2


def test_keyword_verify_on_empty_evidence_marks_missing() -> None:
    result = keyword_verify_evidence("Anything?", [])

    assert result.supported_chunk_ids == []
    assert result.missing_subclaims
    assert result.confidence < 0.2
