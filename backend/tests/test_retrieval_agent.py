"""Tests for run_retrieval_agent: agent path, multi-tool-call mock, and fallback."""

from datetime import date
from types import SimpleNamespace
from typing import Any, cast

import pytest
from rag_common.config import Settings
from rag_common.schemas import QueryFilters
from rag_common.usage import TokenUsage
from rag_retrieval import retrieval_tool
from rag_retrieval.hybrid import RetrievedChunk
from rag_retrieval.planning import RetrievalPlan
from rag_retrieval.retrieval_tool import (
    RetrievalAgentOutput,
    perform_retrieve_evidence,
    run_retrieval_agent,
)


def _agent_unavailable_settings() -> Settings:
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
            hyde_enabled=False,
            embedding_dimension=1024,
            retrieval_agent_tool_call_budget=4,
        ),
    )


def _agent_available_settings() -> Settings:
    return cast(
        "Settings",
        SimpleNamespace(
            allow_mock_providers=False,
            openrouter_api_key=SimpleNamespace(get_secret_value=lambda: "sk-or"),
            openrouter_embedding_model="mock-embedding",
            zai_api_key=SimpleNamespace(get_secret_value=lambda: "sk-zai"),
            zai_chat_model="glm-4.7",
            zai_base_url="https://api.z.ai/api/paas/v4",
            evidence_top_k=8,
            hyde_enabled=False,
            embedding_dimension=1024,
            retrieval_agent_tool_call_budget=4,
            eval_temperature_zero=False,
        ),
    )


def _chunk(chunk_id: str, ticker: str, page: int) -> RetrievedChunk:
    chunk = SimpleNamespace(
        id=chunk_id, text=f"{ticker} text page {page}", page_start=page, page_end=page, contains_table=False
    )
    document = SimpleNamespace(id=f"doc-{chunk_id}", ticker=ticker, filing_date=date(2024, 9, 28), form_type="10-K")
    return cast(
        "RetrievedChunk",
        SimpleNamespace(
            chunk=chunk,
            document=document,
            score=0.9,
            semantic_rank=1,
            lexical_rank=None,
            rerank_score=0.9,
        ),
    )


def _stub_hybrid_retrieve(monkeypatch: pytest.MonkeyPatch, ticker_to_chunks: dict[str, list[RetrievedChunk]]) -> None:
    """Patch hybrid_retrieve to return chunks based on the ticker filter the tool passed in.

    Returns all chunks across all tickers when no ticker filter is supplied, so the
    fallback path (which has no per-ticker iteration) still has something to verify.
    """

    def fake(
        _session: object,
        *,
        dataset_id: str,  # noqa: ARG001
        question: str,  # noqa: ARG001
        filters: QueryFilters,  # noqa: ARG001
        plan: RetrievalPlan,
        top_k: int,
        settings: Settings,  # noqa: ARG001
        semantic_query: str | None = None,  # noqa: ARG001
    ) -> tuple[list[RetrievedChunk], dict[str, Any], TokenUsage, TokenUsage]:
        if plan.target_tickers:
            chunks: list[RetrievedChunk] = []
            for ticker in plan.target_tickers:
                chunks.extend(ticker_to_chunks.get(ticker, []))
        else:
            chunks = [c for sub in ticker_to_chunks.values() for c in sub]
        return (
            chunks[:top_k],
            {"embedding_model": "mock"},
            TokenUsage(prompt_tokens=10, total_tokens=10, model="mock"),
            TokenUsage(prompt_tokens=5, total_tokens=5, model="mock-rerank"),
        )

    monkeypatch.setattr(retrieval_tool, "hybrid_retrieve", fake)


class _FakeAgent:
    """Stand-in for ``Agent.run_sync`` that simulates a scripted sequence of tool calls.

    Each entry in ``tool_call_args`` is a kwargs dict forwarded to
    ``perform_retrieve_evidence`` against the live ``deps``. After replaying all calls,
    the fake returns the supplied ``final_output`` as ``result.output``.
    """

    def __init__(self, tool_call_args: list[dict[str, Any]], final_output: RetrievalAgentOutput) -> None:
        self.tool_call_args = tool_call_args
        self.final_output = final_output
        self.calls: list[dict[str, Any]] = []

    def run_sync(self, prompt: str, *, deps: object, usage_limits: object) -> object:  # noqa: ARG002
        self.calls.append({"prompt": prompt})
        for kwargs in self.tool_call_args:
            perform_retrieve_evidence(cast("Any", deps), **kwargs)
        return SimpleNamespace(output=self.final_output)


def test_agent_unavailable_uses_heuristic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [_chunk("c1", "AAPL", 10), _chunk("c2", "AAPL", 11)]
    _stub_hybrid_retrieve(monkeypatch, {"AAPL": chunks})
    settings = _agent_unavailable_settings()

    result, metadata, agent_chat_usage = run_retrieval_agent(
        cast("Any", SimpleNamespace()),
        dataset_id="d1",
        question="What was Apple's revenue?",
        filters=QueryFilters(),
        known_tickers={"AAPL"},
        settings=settings,
    )

    assert metadata["agent_used"] is False
    assert metadata["fallback_reason"] == "agent_unavailable"
    assert agent_chat_usage.is_empty()
    assert [c.chunk.id for c in result.chunks] == ["c1", "c2"]
    # Heuristic fallback uses a single tool_call entry from the keyword-verifier branch.
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool"] == "heuristic-hybrid_retrieve"
    # Embedding/rerank usage from hybrid_retrieve flows through. HyDE was off.
    assert result.embedding_usage.total_tokens == 10
    assert result.rerank_usage.total_tokens == 5
    assert result.hyde_usage.is_empty()


def test_agent_path_runs_multiple_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    aapl = [_chunk("aapl-1", "AAPL", 10)]
    msft = [_chunk("msft-1", "MSFT", 22)]
    _stub_hybrid_retrieve(monkeypatch, {"AAPL": aapl, "MSFT": msft})

    final_output = RetrievalAgentOutput(
        selected_chunk_ids=["aapl-1", "msft-1"],
        target_tickers=["AAPL", "MSFT"],
        forms=["10-K"],
        metrics=["R&D"],
        query_type="comparison",
        latest=True,
        subquestions=["What is AAPL R&D?", "What is MSFT R&D?"],
        confidence=0.85,
        reasoning="one call per company",
    )
    fake = _FakeAgent(
        tool_call_args=[
            {"query": "AAPL R&D", "tickers": ["AAPL"], "use_hyde": False},
            {"query": "MSFT R&D", "tickers": ["MSFT"], "use_hyde": False},
        ],
        final_output=final_output,
    )
    monkeypatch.setattr(retrieval_tool, "build_retrieval_agent", lambda _settings: fake)

    settings = _agent_available_settings()
    result, metadata, agent_chat_usage = run_retrieval_agent(
        cast("Any", SimpleNamespace()),
        dataset_id="d1",
        question="Compare AAPL vs MSFT R&D",
        filters=QueryFilters(),
        known_tickers={"AAPL", "MSFT"},
        settings=settings,
    )

    assert metadata["agent_used"] is True
    assert metadata["tool_call_count"] == 2
    assert [c.chunk.id for c in result.chunks] == ["aapl-1", "msft-1"]
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0]["tickers"] == ["AAPL"]
    assert result.tool_calls[1]["tickers"] == ["MSFT"]
    # Embedding/rerank usage aggregates across both tool calls.
    assert result.embedding_usage.total_tokens == 20
    assert result.rerank_usage.total_tokens == 10
    assert agent_chat_usage.is_empty()  # _FakeAgent doesn't surface usage()
    # Agent's claimed tickers/forms are intersected with known_tickers + VALID_FORMS.
    assert result.output.target_tickers == ["AAPL", "MSFT"]
    assert result.output.forms == ["10-K"]


def test_agent_failure_falls_back_to_heuristic(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [_chunk("c1", "AAPL", 10)]
    _stub_hybrid_retrieve(monkeypatch, {"AAPL": chunks})

    class _Boom:
        def run_sync(self, _prompt: str, *, deps: object, usage_limits: object) -> object:  # noqa: ARG002
            from rag_common.providers.openrouter import ProviderError

            raise ProviderError("503 upstream")

    monkeypatch.setattr(retrieval_tool, "build_retrieval_agent", lambda _settings: _Boom())

    settings = _agent_available_settings()
    result, metadata, agent_chat_usage = run_retrieval_agent(
        cast("Any", SimpleNamespace()),
        dataset_id="d1",
        question="Apple revenue?",
        filters=QueryFilters(),
        known_tickers={"AAPL"},
        settings=settings,
    )

    assert metadata["agent_used"] is False
    assert metadata["fallback_reason"] == "agent_error"
    error_value = metadata["error"]
    assert isinstance(error_value, str)
    assert "ProviderError" in error_value
    assert agent_chat_usage.is_empty()
    assert [c.chunk.id for c in result.chunks] == ["c1"]


def test_agent_budget_exhaustion_falls_back_to_heuristic(monkeypatch: pytest.MonkeyPatch) -> None:
    # UsageLimitExceeded is a sibling of UnexpectedModelBehavior under AgentRunError,
    # not a subclass, so it must be explicitly retryable for the heuristic fallback to
    # kick in when the agent over-spends its tool_calls_limit / request_limit budget.
    chunks = [_chunk("c1", "AAPL", 10)]
    _stub_hybrid_retrieve(monkeypatch, {"AAPL": chunks})

    class _OverBudget:
        def run_sync(self, _prompt: str, *, deps: object, usage_limits: object) -> object:  # noqa: ARG002
            from pydantic_ai.exceptions import UsageLimitExceeded

            raise UsageLimitExceeded("The next request would exceed the tool_calls_limit of 4")

    monkeypatch.setattr(retrieval_tool, "build_retrieval_agent", lambda _settings: _OverBudget())

    settings = _agent_available_settings()
    result, metadata, agent_chat_usage = run_retrieval_agent(
        cast("Any", SimpleNamespace()),
        dataset_id="d1",
        question="Compare AAPL vs MSFT R&D over five years",
        filters=QueryFilters(),
        known_tickers={"AAPL"},
        settings=settings,
    )

    assert metadata["agent_used"] is False
    assert metadata["fallback_reason"] == "agent_error"
    error_value = metadata["error"]
    assert isinstance(error_value, str)
    assert "UsageLimitExceeded" in error_value
    assert agent_chat_usage.is_empty()
    assert [c.chunk.id for c in result.chunks] == ["c1"]
    # Heuristic fallback shape: one synthesized tool_call entry from the keyword path.
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool"] == "heuristic-hybrid_retrieve"


def test_agent_accepts_json_encoded_list_tickers(monkeypatch: pytest.MonkeyPatch) -> None:
    """glm-4.7 occasionally emits ``tickers='["AAPL"]'`` (a JSON-encoded string) instead
    of an array. The ``_coerce_str_list`` BeforeValidator on the tool parameter should
    transparently decode it so the call doesn't burn the per-tool retry budget on a
    schema mismatch.
    """
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    chunks = [_chunk("aapl-1", "AAPL", 10)]
    _stub_hybrid_retrieve(monkeypatch, {"AAPL": chunks})

    state = {"turn": 0}

    def model_fn(_messages: object, info: AgentInfo) -> ModelResponse:
        state["turn"] += 1
        if state["turn"] == 1:
            # JSON-string-encoded list - the pre-fix shape that blew the retry budget.
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="retrieve_evidence",
                        args={"query": "Apple revenue", "tickers": '["AAPL"]', "use_hyde": False},
                        tool_call_id="call-1",
                    )
                ]
            )
        output_tool_name = info.output_tools[0].name
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=output_tool_name,
                    args={
                        "selected_chunk_ids": ["aapl-1"],
                        "target_tickers": ["AAPL"],
                        "forms": [],
                        "query_type": "fact_lookup",
                        "latest": False,
                        "confidence": 0.8,
                        "reasoning": "ok",
                    },
                    tool_call_id="call-final",
                )
            ]
        )

    monkeypatch.setattr(retrieval_tool, "build_chat_model", lambda _settings=None: FunctionModel(model_fn))

    settings = _agent_available_settings()
    result, metadata, _usage = run_retrieval_agent(
        cast("Any", SimpleNamespace()),
        dataset_id="d1",
        question="Apple revenue?",
        filters=QueryFilters(),
        known_tickers={"AAPL"},
        settings=settings,
    )

    assert metadata["agent_used"] is True
    assert metadata["tool_call_count"] == 1
    assert metadata["tool_retry_count"] == 0
    # The decoded ticker reached perform_retrieve_evidence and produced the expected hit.
    assert [c.chunk.id for c in result.chunks] == ["aapl-1"]


def test_agent_recovers_from_two_modelretries(monkeypatch: pytest.MonkeyPatch) -> None:
    """With tool_retries=2, the agent survives two ModelRetry raises before a clean call.

    Uses pydantic-ai's real retry machinery via FunctionModel (the _FakeAgent fixture used
    elsewhere short-circuits the tool_manager and never exercises the retry counter). The
    script: hybrid_retrieve raises twice (each turns into ModelRetry inside
    perform_retrieve_evidence), then succeeds on the third call. With tool_retries=1
    (pydantic-ai default) the second ModelRetry would surface as UnexpectedModelBehavior;
    with tool_retries=2 the third call goes through.
    """
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    chunks = [_chunk("aapl-1", "AAPL", 10)]

    hr_state = {"calls": 0}

    def flaky_hybrid_retrieve(
        _session: object,
        *,
        dataset_id: str,  # noqa: ARG001
        question: str,  # noqa: ARG001
        filters: QueryFilters,  # noqa: ARG001
        plan: RetrievalPlan,
        top_k: int,
        settings: Settings,  # noqa: ARG001
        semantic_query: str | None = None,  # noqa: ARG001
    ) -> tuple[list[RetrievedChunk], dict[str, Any], TokenUsage, TokenUsage]:
        hr_state["calls"] += 1
        if hr_state["calls"] <= 2:
            raise RuntimeError(f"pgvector transient blip #{hr_state['calls']}")
        return (chunks[:top_k], {"trace": "ok", "tickers": plan.target_tickers}, TokenUsage(), TokenUsage())

    monkeypatch.setattr(retrieval_tool, "hybrid_retrieve", flaky_hybrid_retrieve)

    state = {"turn": 0}

    def model_fn(_messages: object, info: AgentInfo) -> ModelResponse:
        state["turn"] += 1
        if state["turn"] <= 3:
            # Same good filters every turn; hybrid_retrieve decides whether to fail.
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="retrieve_evidence",
                        args={"query": "Apple R&D", "tickers": ["AAPL"], "use_hyde": False},
                        tool_call_id=f"call-{state['turn']}",
                    )
                ]
            )
        # Final turn: emit RetrievalAgentOutput via the agent's output tool.
        output_tool_name = info.output_tools[0].name
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=output_tool_name,
                    args={
                        "selected_chunk_ids": ["aapl-1"],
                        "target_tickers": ["AAPL"],
                        "forms": [],
                        "query_type": "fact_lookup",
                        "latest": False,
                        "confidence": 0.8,
                        "reasoning": "Recovered after two transient hybrid_retrieve failures.",
                    },
                    tool_call_id="call-final",
                )
            ]
        )

    monkeypatch.setattr(retrieval_tool, "build_chat_model", lambda _settings=None: FunctionModel(model_fn))

    settings = cast(
        "Settings",
        SimpleNamespace(
            allow_mock_providers=False,
            openrouter_api_key=SimpleNamespace(get_secret_value=lambda: "sk-or"),
            openrouter_embedding_model="mock-embedding",
            zai_api_key=SimpleNamespace(get_secret_value=lambda: "sk-zai"),
            zai_chat_model="glm-4.7",
            zai_base_url="https://api.z.ai/api/paas/v4",
            evidence_top_k=8,
            hyde_enabled=False,
            embedding_dimension=1024,
            retrieval_agent_tool_call_budget=4,
            eval_temperature_zero=False,
        ),
    )
    result, metadata, _usage = run_retrieval_agent(
        cast("Any", SimpleNamespace()),
        dataset_id="d1",
        question="What did Apple spend on R&D?",
        filters=QueryFilters(),
        known_tickers={"AAPL"},
        settings=settings,
    )

    assert metadata["agent_used"] is True
    # Two retries from hybrid_retrieve failures plus one successful call = 3 total.
    assert metadata["tool_call_count"] == 3
    assert metadata["tool_retry_count"] == 2
    assert [call.get("error_class") for call in result.tool_calls] == ["RuntimeError", "RuntimeError", None]
    assert [c.chunk.id for c in result.chunks] == ["aapl-1"]


def test_agent_with_no_selected_ids_falls_back_to_retrieved(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [_chunk("c1", "AAPL", 10), _chunk("c2", "AAPL", 11), _chunk("c3", "AAPL", 12)]
    _stub_hybrid_retrieve(monkeypatch, {"AAPL": chunks})

    # Agent emits empty selected_chunk_ids - safety net should pick chunks from chunk_lookup.
    final_output = RetrievalAgentOutput(
        selected_chunk_ids=[],
        target_tickers=["AAPL"],
        query_type="fact_lookup",
        reasoning="agent forgot to select",
    )
    fake = _FakeAgent(
        tool_call_args=[{"query": "Apple revenue", "tickers": ["AAPL"], "use_hyde": False}],
        final_output=final_output,
    )
    monkeypatch.setattr(retrieval_tool, "build_retrieval_agent", lambda _settings: fake)

    settings = _agent_available_settings()
    result, _meta, _usage = run_retrieval_agent(
        cast("Any", SimpleNamespace()),
        dataset_id="d1",
        question="Q?",
        filters=QueryFilters(),
        known_tickers={"AAPL"},
        settings=settings,
    )

    # Safety net: when selected_chunk_ids is empty, fall back to top-of-lookup ranked chunks.
    assert {c.chunk.id for c in result.chunks} == {"c1", "c2", "c3"}
    # And ``output.selected_chunk_ids`` is backfilled to match the materialized chunks so
    # the verifier section of the trace reflects the evidence that actually fed the
    # answer (previously it would show "0 supported" despite real chunks being used).
    assert list(result.output.selected_chunk_ids) == [c.chunk.id for c in result.chunks]
