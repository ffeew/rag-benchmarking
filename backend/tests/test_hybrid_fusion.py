"""Unit tests for ``rrf_fuse_ranked_lists`` (multi-query RRF fusion)."""

from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

from rag_retrieval.hybrid import RetrievedChunk, rrf_fuse_ranked_lists

if TYPE_CHECKING:
    from rag_common.db import models


def _chunk(chunk_id: str, *, score: float = 1.0, rerank: float | None = None) -> RetrievedChunk:
    """Build a RetrievedChunk with MagicMock chunk/document; only chunk.id is read by the fuser."""
    fake_chunk = MagicMock()
    fake_chunk.id = chunk_id
    fake_document = MagicMock()
    return RetrievedChunk(
        chunk=cast("models.Chunk", fake_chunk),
        document=cast("models.Document", fake_document),
        score=score,
        semantic_rank=None,
        lexical_rank=None,
        rerank_score=rerank,
    )


def test_rrf_fuse_returns_empty_for_empty_input() -> None:
    assert rrf_fuse_ranked_lists([], limit=10) == []
    assert rrf_fuse_ranked_lists([[]], limit=10) == []


def test_rrf_fuse_single_list_preserves_order() -> None:
    chunks = [_chunk("a"), _chunk("b"), _chunk("c")]
    fused = rrf_fuse_ranked_lists([chunks], limit=10)

    assert [item.chunk.id for item in fused] == ["a", "b", "c"]


def test_rrf_fuse_rewards_chunks_appearing_in_multiple_lists() -> None:
    # ``a`` is rank-1 in list 1 and rank-1 in list 2 -> should dominate ``b`` which only
    # appears once at rank-1, despite ``b`` having an equal solo rank.
    list1 = [_chunk("a"), _chunk("b")]
    list2 = [_chunk("a"), _chunk("c")]
    fused = rrf_fuse_ranked_lists([list1, list2], limit=3)

    assert fused[0].chunk.id == "a"
    assert {fused[1].chunk.id, fused[2].chunk.id} == {"b", "c"}


def test_rrf_fuse_respects_rank_in_score() -> None:
    # Rank-1 in both lists must outscore rank-2 in both lists.
    list1 = [_chunk("top"), _chunk("low")]
    list2 = [_chunk("top"), _chunk("low")]
    fused = rrf_fuse_ranked_lists([list1, list2], limit=2)

    assert [item.chunk.id for item in fused] == ["top", "low"]
    assert fused[0].score > fused[1].score


def test_rrf_fuse_preserves_best_rerank_score() -> None:
    # First sighting of ``a`` has no rerank score; second sighting has 0.91. The fused
    # entry should carry the 0.91 forward so the evidence card downstream still
    # surfaces the rerank signal.
    list1 = [_chunk("a", rerank=None)]
    list2 = [_chunk("a", rerank=0.91)]
    fused = rrf_fuse_ranked_lists([list1, list2], limit=1)

    assert fused[0].chunk.id == "a"
    assert fused[0].rerank_score == 0.91


def test_rrf_fuse_truncates_to_limit() -> None:
    chunks = [_chunk(f"c{i}") for i in range(10)]
    fused = rrf_fuse_ranked_lists([chunks], limit=3)

    assert len(fused) == 3
