"""Unit tests for the HyDE passage generator."""

from types import SimpleNamespace
from typing import cast

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from rag_common.config import Settings
from rag_retrieval import hyde
from rag_retrieval.hyde import generate_hyde_passage


def _settings(
    *,
    allow_mock: bool = True,
    api_key: object | None = None,
    chat_model: str | None = None,
    hyde_enabled: bool = True,
) -> Settings:
    return cast(
        "Settings",
        SimpleNamespace(
            allow_mock_providers=allow_mock,
            zai_api_key=api_key,
            zai_chat_model=chat_model,
            zai_base_url="https://api.z.ai/api/paas/v4",
            hyde_enabled=hyde_enabled,
        ),
    )


def test_hyde_falls_back_when_kill_switch_off() -> None:
    settings = _settings(hyde_enabled=False)
    passage, metadata, usage = generate_hyde_passage("What was Apple's FY24 revenue?", settings)

    assert passage == "What was Apple's FY24 revenue?"
    assert metadata["agent_used"] is False
    assert metadata["fallback_reason"] == "hyde_disabled"
    assert usage.is_empty()


def test_hyde_falls_back_when_agent_unavailable() -> None:
    settings = _settings(allow_mock=True, api_key=None, chat_model=None)
    passage, metadata, usage = generate_hyde_passage("What was Apple's FY24 revenue?", settings)

    assert passage == "What was Apple's FY24 revenue?"
    assert metadata["agent_used"] is False
    assert metadata["fallback_reason"] == "agent_unavailable"
    assert usage.is_empty()


def test_hyde_returns_passage_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        allow_mock=False,
        api_key=SimpleNamespace(get_secret_value=lambda: "sk-x"),
        chat_model="anthropic/claude-3.5-sonnet",
    )

    hypothetical_text = (
        "For the fiscal year ended September 28, 2024, the Company recorded total net "
        "sales of $383.3 billion, an increase of approximately 2% over the prior year, "
        "primarily driven by growth in Services."
    )

    fake_agent = SimpleNamespace(
        run_sync=lambda _prompt: SimpleNamespace(output=hypothetical_text),
    )
    monkeypatch.setattr(hyde, "_build_hyde_agent_for", lambda _model: fake_agent)

    passage, metadata, usage = generate_hyde_passage("What was Apple's FY24 revenue?", settings)

    assert passage == hypothetical_text
    assert metadata["agent_used"] is True
    assert metadata["model"] == "anthropic/claude-3.5-sonnet"
    assert usage.is_empty()  # SimpleNamespace lacks .usage() so safe_pydantic_ai_usage returns empty


def test_hyde_handles_empty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        allow_mock=False,
        api_key=SimpleNamespace(get_secret_value=lambda: "sk-x"),
        chat_model="anthropic/claude-3.5-sonnet",
    )

    fake_agent = SimpleNamespace(run_sync=lambda _prompt: SimpleNamespace(output="   "))
    monkeypatch.setattr(hyde, "_build_hyde_agent_for", lambda _model: fake_agent)

    passage, metadata, usage = generate_hyde_passage("Q?", settings)

    assert passage == "Q?"
    assert metadata["agent_used"] is False
    assert metadata["fallback_reason"] == "empty_passage"
    assert usage.is_empty()


def test_hyde_falls_back_on_agent_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        allow_mock=False,
        api_key=SimpleNamespace(get_secret_value=lambda: "sk-x"),
        chat_model="anthropic/claude-3.5-sonnet",
    )

    def _boom(_prompt: str) -> SimpleNamespace:
        raise ModelHTTPError(status_code=503, model_name="anthropic/claude-3.5-sonnet", body="upstream 503")

    fake_agent = SimpleNamespace(run_sync=_boom)
    monkeypatch.setattr(hyde, "_build_hyde_agent_for", lambda _model: fake_agent)

    passage, metadata, usage = generate_hyde_passage("Q?", settings)

    assert passage == "Q?"
    assert metadata["agent_used"] is False
    assert "ModelHTTPError" in str(metadata["error"])
    assert usage.is_empty()
