"""Tests for the channel-gating behavior in ``hybrid_retrieve``.

Verifies that ``semantic_candidates=0`` and ``full_text_candidates=0`` produce
true lexical-only / semantic-only retrieval, without spuriously executing the
disabled channel's network call or SQL query.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from rag_common.config import Settings
from rag_common.providers.openrouter import EmbeddingResult, ProviderMetadata
from rag_common.schemas import QueryFilters
from rag_retrieval.hybrid import hybrid_retrieve
from rag_retrieval.planning import RetrievalPlan
from sqlalchemy.orm import Session


def _settings(*, semantic: int, lexical: int) -> Settings:
    return Settings(
        api_bearer_token=SecretStr("test-token"),
        allow_mock_providers=True,
        semantic_candidates=semantic,
        full_text_candidates=lexical,
        fused_candidates=20,
        evidence_top_k=8,
        rerank_candidates=20,
        reranker_enabled=False,
    )


def _empty_plan() -> RetrievalPlan:
    return RetrievalPlan(
        target_tickers=[],
        forms=[],
        filing_date_start=None,
        filing_date_end=None,
        metrics=[],
        subquestions=[],
        query_type=None,
        latest=False,
        ambiguity=None,
        reasoning=None,
    )


def _fake_session() -> MagicMock:
    """A Session stub whose ``execute`` returns an empty result. Lets us check call counts."""

    session = MagicMock(spec=Session)
    execute_result = MagicMock()
    execute_result.all.return_value = []
    session.execute.return_value = execute_result
    return session


def test_semantic_only_skips_lexical_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(semantic=20, lexical=0)
    session = _fake_session()

    embed_calls: list[Any] = []
    def fake_embeddings(self: Any, texts: list[str], **_: Any) -> EmbeddingResult:
        embed_calls.append(texts)
        return EmbeddingResult(
            vectors=[[0.0] * settings.embedding_dimension],
            metadata=ProviderMetadata(provider="mock", model="mock-embed"),
        )

    from rag_common.providers.openrouter import OpenRouterClient

    monkeypatch.setattr(OpenRouterClient, "embeddings", fake_embeddings)

    _, trace, _, _ = hybrid_retrieve(
        session,
        dataset_id="d1",
        question="What is X?",
        filters=QueryFilters(),
        plan=_empty_plan(),
        top_k=5,
        settings=settings,
    )
    assert len(embed_calls) == 1, "semantic channel should run exactly once"
    # session.execute is called once for the semantic SQL only.
    assert session.execute.call_count == 1
    assert trace["semantic_enabled"] is True
    assert trace["lexical_enabled"] is False


def test_lexical_only_skips_embedding_and_vector_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(semantic=0, lexical=20)
    session = _fake_session()

    embed_calls: list[Any] = []

    from rag_common.providers.openrouter import OpenRouterClient

    def fake_embeddings(self: Any, texts: list[str], **_: Any) -> EmbeddingResult:
        embed_calls.append(texts)
        raise AssertionError("embeddings should NOT be called when semantic_candidates=0")

    monkeypatch.setattr(OpenRouterClient, "embeddings", fake_embeddings)

    _, trace, embed_usage, _ = hybrid_retrieve(
        session,
        dataset_id="d1",
        question="What is Y?",
        filters=QueryFilters(),
        plan=_empty_plan(),
        top_k=5,
        settings=settings,
    )
    assert embed_calls == []
    # Only the lexical SQL fires.
    assert session.execute.call_count == 1
    assert trace["semantic_enabled"] is False
    assert trace["lexical_enabled"] is True
    assert trace["embedding_model"] is None
    assert embed_usage.total_tokens == 0


def test_both_channels_zero_raises() -> None:
    settings = _settings(semantic=0, lexical=0)
    session = _fake_session()
    with pytest.raises(ValueError, match="at least one channel"):
        hybrid_retrieve(
            session,
            dataset_id="d1",
            question="What?",
            filters=QueryFilters(),
            plan=_empty_plan(),
            top_k=5,
            settings=settings,
        )
