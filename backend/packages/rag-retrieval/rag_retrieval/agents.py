import logging
from collections.abc import Callable
from functools import lru_cache

import httpx
from pydantic_ai import Agent, UserError
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from rag_common.config import Settings, get_settings
from rag_common.providers.openrouter import ProviderError
from rag_common.usage import TokenUsage

logger = logging.getLogger(__name__)


# Transient errors that warrant a fall-back to the deterministic path. Programmer
# errors (``UserError`` — wrong deps_type, missing tool registration, etc.) are
# deliberately excluded: catching them would silently mask agent-construction
# regressions in CI and let production drift onto the heuristic path for days
# without any visible error. Let those propagate.
#
# ``UsageLimitExceeded`` is included so that an agent which over-spends its
# ``UsageLimits`` budget (tool_calls_limit / request_limit) degrades to the
# heuristic path instead of crashing the query. It is a sibling of
# ``UnexpectedModelBehavior`` under ``AgentRunError``, not a subclass, so it
# must be listed explicitly.
AGENT_RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    ModelHTTPError,
    ProviderError,
    httpx.HTTPError,
)

# Re-exported for test imports that still reference the symbol; kept distinct
# so a future maintainer cannot accidentally fold it back into the retryable set.
AGENT_PROGRAMMER_ERRORS: tuple[type[BaseException], ...] = (UserError,)


def agent_available(settings: Settings | None = None) -> bool:
    resolved = settings or get_settings()
    if resolved.allow_mock_providers:
        return False
    if resolved.zai_api_key is None:
        return False
    return bool(resolved.zai_chat_model)


def judge_available(settings: Settings | None = None) -> bool:
    resolved = settings or get_settings()
    if resolved.allow_mock_providers:
        return False
    if resolved.zai_api_key is None:
        return False
    return bool(resolved.zai_judge_model)


@lru_cache(maxsize=4)
def _zai_provider(api_key: str, base_url: str) -> OpenAIProvider:
    return OpenAIProvider(api_key=api_key, base_url=base_url)


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
    if resolved.zai_api_key is None:
        raise ProviderError("ZAI_API_KEY is not configured")
    if not resolved.zai_chat_model:
        raise ProviderError("ZAI_CHAT_MODEL is not configured")
    provider = _zai_provider(resolved.zai_api_key.get_secret_value(), resolved.zai_base_url)
    return OpenAIChatModel(resolved.zai_chat_model, provider=provider)


def build_judge_model(settings: Settings | None = None) -> Model:
    resolved = settings or get_settings()
    if resolved.zai_api_key is None:
        raise ProviderError("ZAI_API_KEY is not configured")
    if not resolved.zai_judge_model:
        raise ProviderError("ZAI_JUDGE_MODEL is not configured")
    provider = _zai_provider(resolved.zai_api_key.get_secret_value(), resolved.zai_base_url)
    return OpenAIChatModel(resolved.zai_judge_model, provider=provider)


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
    except AGENT_RETRYABLE_ERRORS as exc:
        message = f"{type(exc).__name__}: {exc}"
        # ERROR (not WARNING) because the agent fallback is degraded behavior, not a
        # routine condition. Operators monitoring ERROR-level events should see this.
        logger.error("agent_fallback", extra={"label": label, "error": message})
        return fallback(), False, message, TokenUsage()


def build_agent[D, T](
    *,
    output_type: type[T],
    instructions: str,
    deps_type: type[D] = type(None),  # type: ignore[assignment]
    settings: Settings | None = None,
    name: str | None = None,
    output_retries: int | None = None,
) -> Agent[D, T]:
    """Construct a Pydantic AI agent bound to the configured chat model.

    ``instructions`` is the pydantic-ai successor to ``system_prompt`` for agents
    that do not need their prompt preserved across ``message_history``. Pass
    ``deps_type`` whenever the agent has tools, dynamic ``@agent.instructions``,
    or ``@agent.output_validator`` callbacks that need ``ctx.deps``; defaults to
    ``None`` for context-free agents. ``output_retries`` opts the agent into
    ``ModelRetry``-driven repair from validators (pydantic-ai defaults to 1).
    """
    return Agent(
        model=build_chat_model(settings),
        output_type=output_type,
        instructions=instructions,
        deps_type=deps_type,
        name=name,
        model_settings=deterministic_model_settings(settings),
        output_retries=output_retries,
    )
