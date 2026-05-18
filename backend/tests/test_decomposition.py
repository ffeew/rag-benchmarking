"""Unit tests for the query decomposition module."""

from types import SimpleNamespace
from typing import cast

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from rag_common.config import Settings
from rag_retrieval import decomposition
from rag_retrieval.decomposition import QueryDecomposition, decompose_query


def _settings(
    *,
    allow_mock: bool = True,
    api_key: object | None = None,
    chat_model: str | None = None,
    decomposition_enabled: bool = True,
    max_subquestions: int = 4,
) -> Settings:
    return cast(
        "Settings",
        SimpleNamespace(
            allow_mock_providers=allow_mock,
            zai_api_key=api_key,
            zai_chat_model=chat_model,
            zai_base_url="https://api.z.ai/api/paas/v4",
            query_decomposition_enabled=decomposition_enabled,
            decomposition_max_subquestions=max_subquestions,
        ),
    )


def test_decomposition_falls_back_when_kill_switch_off() -> None:
    settings = _settings(decomposition_enabled=False)
    subquestions, metadata, usage = decompose_query(
        "Compare Apple and Microsoft R&D in FY24.",
        settings,
    )

    assert subquestions == []
    assert metadata["agent_used"] is False
    assert metadata["fallback_reason"] == "decomposition_disabled"
    assert usage.is_empty()


def test_decomposition_falls_back_when_agent_unavailable() -> None:
    settings = _settings(allow_mock=True, api_key=None, chat_model=None)
    subquestions, metadata, usage = decompose_query("Q?", settings)

    assert subquestions == []
    assert metadata["agent_used"] is False
    assert metadata["fallback_reason"] == "agent_unavailable"
    assert usage.is_empty()


def test_decomposition_returns_subquestions_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        allow_mock=False,
        api_key=SimpleNamespace(get_secret_value=lambda: "sk-x"),
        chat_model="anthropic/claude-3.5-sonnet",
    )
    output = QueryDecomposition(
        subquestions=[
            "What was Apple's R&D spend in its latest 10-K?",
            "What was Microsoft's R&D spend in its latest 10-K?",
        ],
    )

    fake_agent = SimpleNamespace(
        run_sync=lambda _prompt, deps=None: SimpleNamespace(output=output),  # noqa: ARG005
    )
    monkeypatch.setattr(decomposition, "_build_decomposer_agent_for", lambda _model: fake_agent)

    subquestions, metadata, usage = decompose_query(
        "Compare Apple and Microsoft R&D in their latest 10-Ks.",
        settings,
    )

    assert subquestions == output.subquestions
    assert metadata["agent_used"] is True
    assert metadata["model"] == "anthropic/claude-3.5-sonnet"
    assert metadata["subquestion_count"] == 2
    assert "truncated_from" not in metadata
    assert usage.is_empty()  # SimpleNamespace lacks .usage so safe_pydantic_ai_usage returns empty


def test_decomposition_truncates_to_max_subquestions(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        allow_mock=False,
        api_key=SimpleNamespace(get_secret_value=lambda: "sk-x"),
        chat_model="anthropic/claude-3.5-sonnet",
        max_subquestions=2,
    )
    output = QueryDecomposition(subquestions=["q1", "q2", "q3", "q4"])

    fake_agent = SimpleNamespace(
        run_sync=lambda _prompt, deps=None: SimpleNamespace(output=output),  # noqa: ARG005
    )
    monkeypatch.setattr(decomposition, "_build_decomposer_agent_for", lambda _model: fake_agent)

    subquestions, metadata, _ = decompose_query("Q?", settings)

    assert subquestions == ["q1", "q2"]
    assert metadata["subquestion_count"] == 2
    assert metadata["truncated_from"] == 4


def test_decomposition_handles_empty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Atomic-question signal: empty subquestion list is the LLM's "do not decompose" reply."""
    settings = _settings(
        allow_mock=False,
        api_key=SimpleNamespace(get_secret_value=lambda: "sk-x"),
        chat_model="anthropic/claude-3.5-sonnet",
    )
    output = QueryDecomposition(subquestions=["", "   "])  # whitespace-only entries are stripped

    fake_agent = SimpleNamespace(
        run_sync=lambda _prompt, deps=None: SimpleNamespace(output=output),  # noqa: ARG005
    )
    monkeypatch.setattr(decomposition, "_build_decomposer_agent_for", lambda _model: fake_agent)

    subquestions, metadata, _ = decompose_query("What was Apple's FY24 revenue?", settings)

    assert subquestions == []
    assert metadata["agent_used"] is False
    assert metadata["fallback_reason"] == "empty_subquestions"


def test_decomposition_falls_back_on_agent_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        allow_mock=False,
        api_key=SimpleNamespace(get_secret_value=lambda: "sk-x"),
        chat_model="anthropic/claude-3.5-sonnet",
    )

    def _boom(_prompt: str, deps: object | None = None) -> SimpleNamespace:  # noqa: ARG001
        raise ModelHTTPError(status_code=503, model_name="anthropic/claude-3.5-sonnet", body="upstream 503")

    fake_agent = SimpleNamespace(run_sync=_boom)
    monkeypatch.setattr(decomposition, "_build_decomposer_agent_for", lambda _model: fake_agent)

    subquestions, metadata, usage = decompose_query("Q?", settings)

    assert subquestions == []
    assert metadata["agent_used"] is False
    assert "ModelHTTPError" in str(metadata["error"])
    assert usage.is_empty()
