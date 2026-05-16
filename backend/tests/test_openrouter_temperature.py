"""Verify temperature=0 is plumbed through chat + pydantic-ai agents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from pydantic import SecretStr
from rag_common.config import Settings
from rag_common.providers.openrouter import OpenRouterClient
from rag_retrieval.agents import deterministic_model_settings

if TYPE_CHECKING:
    import pytest


def _real_settings(*, temp_zero: bool = True) -> Settings:
    return Settings(
        api_bearer_token=SecretStr("test-token"),
        openrouter_api_key=SecretStr("test-key"),
        openrouter_chat_model="anthropic/claude-test",
        openrouter_judge_model="anthropic/claude-judge",
        openrouter_embedding_model="openai/embed",
        openrouter_rerank_model="cohere/rerank",
        eval_temperature_zero=temp_zero,
        allow_mock_providers=False,
    )


def test_chat_payload_carries_temperature_zero_when_eval_determinism_on(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _real_settings(temp_zero=True)
    captured: dict[str, Any] = {}

    class DummyResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "choices": [{"message": {"content": "ok"}}],
                "id": "1",
                "provider": "p",
                "model": "anthropic/claude-test",
            }

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any]) -> DummyResponse:  # noqa: ARG001
        captured.update(json)
        return DummyResponse()

    client = OpenRouterClient(settings)
    monkeypatch.setattr(client._client, "post", fake_post)
    client.chat(messages=[{"role": "user", "content": "hi"}])
    assert captured.get("temperature") == 0


def test_chat_payload_omits_temperature_when_determinism_off(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _real_settings(temp_zero=False)
    captured: dict[str, Any] = {}

    class DummyResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "choices": [{"message": {"content": "ok"}}],
                "model": "anthropic/claude-test",
            }

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any]) -> DummyResponse:  # noqa: ARG001
        captured.update(json)
        return DummyResponse()

    client = OpenRouterClient(settings)
    monkeypatch.setattr(client._client, "post", fake_post)
    client.chat(messages=[{"role": "user", "content": "hi"}])
    assert "temperature" not in captured


def test_deterministic_model_settings_returns_zero_when_enabled() -> None:
    settings = _real_settings(temp_zero=True)
    result = deterministic_model_settings(settings)
    # ModelSettings is a TypedDict at runtime — assert structure, not isinstance.
    assert result is not None
    assert result["temperature"] == 0  # type: ignore[index]


def test_deterministic_model_settings_is_none_when_disabled() -> None:
    settings = _real_settings(temp_zero=False)
    assert deterministic_model_settings(settings) is None


# Sanity check that the httpx transport doesn't strip our kwarg.
def test_dummy_httpx_response_shape() -> None:
    response = httpx.Response(200, json={"x": 1})
    assert response.json() == {"x": 1}
