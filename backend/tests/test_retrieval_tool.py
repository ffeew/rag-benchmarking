"""Unit tests for the retrieve_evidence tool body."""

from datetime import date
from types import SimpleNamespace
from typing import cast

import pytest
from rag_common.config import Settings
from rag_common.enums import QueryType
from rag_common.schemas import QueryFilters
from rag_common.usage import TokenUsage
from rag_retrieval import retrieval_tool
from rag_retrieval.hybrid import RetrievedChunk
from rag_retrieval.planning import RetrievalPlan
from rag_retrieval.retrieval_tool import (
    RetrievalAgentDeps,
    _coerce_str_list,
    perform_retrieve_evidence,
)


def _settings(*, hyde_enabled: bool = False, embedding_dim: int = 1024) -> Settings:
    """Stub settings.

    HyDE is off by default so the tool exercises only the retrieval path; tests that
    care about HyDE turn it on explicitly via the ``use_hyde`` tool parameter and
    monkeypatch ``generate_hyde_passage``.
    """
    return cast(
        "Settings",
        SimpleNamespace(
            allow_mock_providers=True,
            openrouter_api_key=None,
            openrouter_embedding_model="mock-embedding",
            zai_api_key=None,
            zai_chat_model=None,
            zai_base_url="https://api.z.ai/api/paas/v4",
            evidence_top_k=8,
            hyde_enabled=hyde_enabled,
            embedding_dimension=embedding_dim,
            retrieval_agent_tool_call_budget=4,
        ),
    )


def _base_plan() -> RetrievalPlan:
    return RetrievalPlan(query_type=QueryType.FACT_LOOKUP)


def _deps(*, known_tickers: set[str], settings: Settings | None = None) -> RetrievalAgentDeps:
    return RetrievalAgentDeps(
        session=cast("object", SimpleNamespace()),  # type: ignore[arg-type]
        dataset_id="d1",
        settings=settings or _settings(),
        user_question="Q?",
        base_filters=QueryFilters(),
        base_plan=_base_plan(),
        known_tickers=frozenset(known_tickers),
    )


def _chunk(chunk_id: str, ticker: str, page: int, text: str) -> RetrievedChunk:
    chunk = SimpleNamespace(
        id=chunk_id,
        text=text,
        page_start=page,
        page_end=page,
        contains_table=False,
    )
    document = SimpleNamespace(
        id=f"doc-{chunk_id}",
        ticker=ticker,
        filing_date=date(2024, 9, 28),
        form_type="10-K",
    )
    return cast(
        "RetrievedChunk",
        SimpleNamespace(
            chunk=chunk,
            document=document,
            score=0.9,
            semantic_rank=1,
            lexical_rank=None,
            rerank_score=0.95,
        ),
    )


def _fake_hybrid_retrieve_factory(
    retrieved: list[RetrievedChunk],
) -> tuple[object, dict[str, object]]:
    captured: dict[str, object] = {}

    def fake_hybrid_retrieve(
        _session: object,
        *,
        dataset_id: str,
        question: str,
        filters: QueryFilters,
        plan: RetrievalPlan,
        top_k: int,
        settings: Settings,
        semantic_query: str | None = None,
    ) -> tuple[list[RetrievedChunk], dict[str, object], TokenUsage, TokenUsage]:
        captured["dataset_id"] = dataset_id
        captured["question"] = question
        captured["semantic_query"] = semantic_query
        captured["filters"] = filters
        captured["plan"] = plan
        captured["top_k"] = top_k
        captured["settings"] = settings
        trace = {"embedding_model": "mock", "semantic_query_used": semantic_query is not None}
        embedding_usage = TokenUsage(prompt_tokens=10, total_tokens=10, model="mock")
        rerank_usage = TokenUsage(prompt_tokens=5, total_tokens=5, model="mock-rerank")
        return retrieved, trace, embedding_usage, rerank_usage

    return fake_hybrid_retrieve, captured


def test_tool_drops_unknown_tickers_and_invalid_forms(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_retrieve, captured = _fake_hybrid_retrieve_factory([_chunk("c1", "AAPL", 10, "Apple revenue")])
    monkeypatch.setattr(retrieval_tool, "hybrid_retrieve", fake_retrieve)

    deps = _deps(known_tickers={"AAPL", "MSFT"})
    hits = perform_retrieve_evidence(
        deps,
        "Apple revenue",
        tickers=["AAPL", "GOOGL", "FAKE"],  # only AAPL is known
        form_types=["10-K", "S-1"],  # only 10-K is valid
        use_hyde=False,
    )

    assert len(hits) == 1
    plan = cast("RetrievalPlan", captured["plan"])
    assert plan.target_tickers == ["AAPL"]
    assert plan.forms == ["10-K"]
    # Tool call log reflects normalized filters.
    assert deps.tool_calls[-1]["tickers"] == ["AAPL"]
    assert deps.tool_calls[-1]["form_types"] == ["10-K"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Real glm-4.7 failure mode: tickers serialized as a JSON string literal.
        ('["AAPL"]', ["AAPL"]),
        ('["AAPL", "MSFT"]', ["AAPL", "MSFT"]),
        ('  ["AAPL"]  ', ["AAPL"]),  # tolerates leading/trailing whitespace
        # Already-correct shapes pass through untouched.
        (["AAPL"], ["AAPL"]),
        (None, None),
        # Plain strings are not coerced (validator will surface the type error).
        ("AAPL", "AAPL"),
        # Malformed JSON in list-shaped braces falls through as-is.
        ("[AAPL]", "[AAPL]"),
    ],
)
def test_coerce_str_list_handles_json_encoded_arrays(raw: object, expected: object) -> None:
    assert _coerce_str_list(raw) == expected


def test_tool_silently_drops_when_all_filters_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """When every proposed filter is out-of-corpus the tool falls back to no filter.

    Previously this raised ModelRetry, which burned the per-tool retry budget on
    stochastic ticker hallucinations. The new contract is to silently drop and let
    the unfiltered query run, matching the docstring's "silently dropped" wording.
    """
    fake_retrieve, captured = _fake_hybrid_retrieve_factory([_chunk("c1", "AAPL", 10, "Apple revenue")])
    monkeypatch.setattr(retrieval_tool, "hybrid_retrieve", fake_retrieve)

    deps = _deps(known_tickers={"AAPL"})
    hits = perform_retrieve_evidence(
        deps,
        "Apple revenue",
        tickers=["FAKE1", "FAKE2"],
        form_types=["S-1"],
        use_hyde=False,
    )

    # Tool succeeded with no filter — no ModelRetry raised.
    assert len(hits) == 1
    plan = cast("RetrievalPlan", captured["plan"])
    assert plan.target_tickers == []
    assert plan.forms == []
    # The call entry surfaces the dropped values for trace-side debugging.
    last = deps.tool_calls[-1]
    assert last["dropped_tickers"] == ["FAKE1", "FAKE2"]
    assert last["dropped_forms"] == ["S-1"]
    assert last.get("error_class") is None
    assert last["returned"] == 1
    # And the new output-enrichment fields are populated.
    assert last["returned_chunk_ids"] == ["c1"]
    assert last["returned_tickers"] == ["AAPL"]
    assert last["returned_forms"] == ["10-K"]
    # ``candidates`` carries the per-rank detail the trace UI renders.
    assert len(last["candidates"]) == 1
    cand = last["candidates"][0]
    assert cand["rank"] == 1
    assert cand["chunk_id"] == "c1"
    assert cand["ticker"] == "AAPL"
    assert cand["form_type"] == "10-K"
    assert cand["page_start"] == 10
    assert isinstance(cand["score"], float)
    assert cand["snippet"]  # non-empty


def test_tool_clamps_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_retrieve, captured = _fake_hybrid_retrieve_factory([])
    monkeypatch.setattr(retrieval_tool, "hybrid_retrieve", fake_retrieve)

    deps = _deps(known_tickers={"AAPL"})
    perform_retrieve_evidence(deps, "x", top_k=50, use_hyde=False)
    high = captured["top_k"]
    assert high == 12  # upper clamp

    perform_retrieve_evidence(deps, "x", top_k=0, use_hyde=False)
    low = captured["top_k"]
    assert low == 1  # lower clamp


def test_tool_populates_lookup_and_usage_records(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [_chunk("c1", "AAPL", 10, "Revenue text"), _chunk("c2", "AAPL", 11, "Margin text")]
    fake_retrieve, _ = _fake_hybrid_retrieve_factory(chunks)
    monkeypatch.setattr(retrieval_tool, "hybrid_retrieve", fake_retrieve)

    deps = _deps(known_tickers={"AAPL"})
    hits = perform_retrieve_evidence(deps, "q", use_hyde=False)

    assert {hit.chunk_id for hit in hits} == {"c1", "c2"}
    assert set(deps.chunk_lookup.keys()) == {"c1", "c2"}
    assert len(deps.embedding_usage_records) == 1
    assert len(deps.rerank_usage_records) == 1
    assert len(deps.hyde_usage_records) == 0  # HyDE disabled


def test_tool_records_failure_and_raises_model_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic_ai.exceptions import ModelRetry

    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("pgvector exploded")

    monkeypatch.setattr(retrieval_tool, "hybrid_retrieve", boom)
    deps = _deps(known_tickers={"AAPL"})

    with pytest.raises(ModelRetry):
        perform_retrieve_evidence(deps, "q", use_hyde=False)

    error_value = deps.tool_calls[-1]["error"]
    assert isinstance(error_value, str)
    assert error_value.startswith("RuntimeError")
    assert deps.tool_calls[-1]["returned"] == 0
    # No usage records when retrieval failed before producing any.
    assert deps.embedding_usage_records == []
    assert deps.rerank_usage_records == []


def test_tool_uses_hyde_passage_for_semantic_query(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_retrieve, captured = _fake_hybrid_retrieve_factory([_chunk("c1", "AAPL", 10, "x")])
    monkeypatch.setattr(retrieval_tool, "hybrid_retrieve", fake_retrieve)

    hypothetical = "For the fiscal year ended September 28, 2024, total net sales were $383.3B."

    def fake_hyde(
        query: str,
        _settings: object,
        *,
        dataset_config: object | None = None,  # noqa: ARG001
    ) -> tuple[str, dict[str, object], TokenUsage]:
        assert query == "Apple revenue FY24"
        return (
            hypothetical,
            {"agent_used": True, "model": "claude"},
            TokenUsage(prompt_tokens=20, total_tokens=20, model="claude"),
        )

    monkeypatch.setattr(retrieval_tool, "generate_hyde_passage", fake_hyde)

    deps = _deps(known_tickers={"AAPL"})
    perform_retrieve_evidence(deps, "Apple revenue FY24", use_hyde=True)

    assert captured["semantic_query"] == hypothetical
    assert captured["question"] == "Apple revenue FY24"  # FTS still uses the original
    assert len(deps.hyde_usage_records) == 1
    assert deps.hyde_usage_records[0].total_tokens == 20
    hyde_meta = deps.tool_calls[-1]["hyde_meta"]
    assert isinstance(hyde_meta, dict)
    assert hyde_meta["agent_used"] is True
