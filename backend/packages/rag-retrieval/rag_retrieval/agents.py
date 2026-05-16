from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

import httpx
from pydantic_ai import Agent, UserError
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings
from rag_common.config import Settings, get_settings
from rag_common.providers.openrouter import ProviderError
from rag_common.usage import TokenUsage

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.models import Model


logger = logging.getLogger(__name__)


_AGENT_RETRYABLE_ERRORS = (
    UnexpectedModelBehavior,
    ModelHTTPError,
    ProviderError,
    httpx.HTTPError,
    UserError,
)


def agent_available(settings: Settings | None = None) -> bool:
    resolved = settings or get_settings()
    if resolved.allow_mock_providers:
        return False
    if resolved.openrouter_api_key is None:
        return False
    return bool(resolved.openrouter_chat_model)


def judge_available(settings: Settings | None = None) -> bool:
    resolved = settings or get_settings()
    if resolved.allow_mock_providers:
        return False
    if resolved.openrouter_api_key is None:
        return False
    return bool(resolved.openrouter_judge_model)


@lru_cache(maxsize=4)
def _provider_for_key(api_key: str) -> OpenRouterProvider:
    return OpenRouterProvider(api_key=api_key)


def deterministic_model_settings(settings: Settings | None = None) -> ModelSettings | None:
    """Return ``ModelSettings(temperature=0)`` when the eval determinism knob is on.

    Used by every Pydantic AI ``Agent`` we build so HyDE / retrieval / verifier /
    generator all run at temperature=0 during evaluation. Returns ``None`` when
    determinism is disabled so the agent falls back to provider defaults.
    """

    resolved = settings or get_settings()
    if not resolved.eval_temperature_zero:
        return None
    return ModelSettings(temperature=0)


def build_chat_model(settings: Settings | None = None) -> Model:
    resolved = settings or get_settings()
    if resolved.openrouter_api_key is None:
        raise ProviderError("OPENROUTER_API_KEY is not configured")
    if not resolved.openrouter_chat_model:
        raise ProviderError("OPENROUTER_CHAT_MODEL is not configured")
    provider = _provider_for_key(resolved.openrouter_api_key.get_secret_value())
    return OpenAIChatModel(resolved.openrouter_chat_model, provider=provider)


def build_judge_model(settings: Settings | None = None) -> Model:
    resolved = settings or get_settings()
    if resolved.openrouter_api_key is None:
        raise ProviderError("OPENROUTER_API_KEY is not configured")
    if not resolved.openrouter_judge_model:
        raise ProviderError("OPENROUTER_JUDGE_MODEL is not configured")
    provider = _provider_for_key(resolved.openrouter_api_key.get_secret_value())
    return OpenAIChatModel(resolved.openrouter_judge_model, provider=provider)


def run_with_fallback[T](
    agent_call: Callable[[], tuple[T, TokenUsage]],
    fallback: Callable[[], T],
    *,
    label: str,
) -> tuple[T, bool, str | None, TokenUsage]:
    """Run an agent call, falling back to a deterministic implementation on failure.

    The agent path must return its result paired with the token usage observed for
    that call so callers can roll usage into the trace. Fallbacks are deterministic
    and produce no usage.

    Returns ``(result, used_agent, error_message, usage)``. ``used_agent`` is ``True``
    only when the agent call returned successfully; any caught exception triggers the
    fallback and the error string is returned for trace persistence.
    """
    try:
        result, usage = agent_call()
        return result, True, None, usage
    except _AGENT_RETRYABLE_ERRORS as exc:
        message = f"{type(exc).__name__}: {exc}"
        logger.warning("agent_fallback", extra={"label": label, "error": message})
        return fallback(), False, message, TokenUsage()


def build_agent[T](
    *,
    output_type: type[T],
    system_prompt: str,
    settings: Settings | None = None,
    name: str | None = None,
) -> Agent[None, T]:
    """Construct a Pydantic AI agent bound to the configured OpenRouter chat model."""
    return Agent(
        model=build_chat_model(settings),
        output_type=output_type,
        system_prompt=system_prompt,
        name=name,
        model_settings=deterministic_model_settings(settings),
    )
