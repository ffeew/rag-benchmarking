"""Token usage tracking shared across the retrieval and evaluation pipelines."""

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["planner", "verifier", "generator", "embedding", "rerank", "judge"]
ROLES: tuple[Role, ...] = ("planner", "verifier", "generator", "embedding", "rerank", "judge")


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    provider: str | None = None
    model: str | None = None

    def is_empty(self) -> bool:
        return self.total_tokens == 0 and self.prompt_tokens == 0 and self.completion_tokens == 0


class RoleUsage(BaseModel):
    planner: TokenUsage = Field(default_factory=TokenUsage)
    verifier: TokenUsage = Field(default_factory=TokenUsage)
    generator: TokenUsage = Field(default_factory=TokenUsage)
    embedding: TokenUsage = Field(default_factory=TokenUsage)
    rerank: TokenUsage = Field(default_factory=TokenUsage)
    judge: TokenUsage = Field(default_factory=TokenUsage)


def from_openrouter_usage(
    raw: dict[str, int] | dict[str, object] | None,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> TokenUsage:
    """Parse an OpenRouter `usage` dict into a typed TokenUsage. Missing fields default to 0."""
    if not raw:
        return TokenUsage(provider=provider, model=model)
    prompt = _coerce_int(raw.get("prompt_tokens"))
    completion = _coerce_int(raw.get("completion_tokens"))
    total = _coerce_int(raw.get("total_tokens"))
    if total == 0:
        total = prompt + completion
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        provider=provider,
        model=model,
    )


def from_pydantic_ai_usage(usage: object, *, provider: str | None = None, model: str | None = None) -> TokenUsage:
    """Parse a pydantic-ai RunUsage object into a typed TokenUsage.

    The pydantic-ai API exposes ``input_tokens``, ``output_tokens``, and ``total_tokens`` on its
    usage objects (the attribute names diverge from OpenRouter's). Read defensively so callers
    don't crash if the upstream API renames or removes a field.
    """
    if usage is None:
        return TokenUsage(provider=provider, model=model)
    input_tokens = _get_int_attr(usage, ("input_tokens", "request_tokens", "prompt_tokens"))
    output_tokens = _get_int_attr(usage, ("output_tokens", "response_tokens", "completion_tokens"))
    total = _get_int_attr(usage, ("total_tokens",))
    if total == 0:
        total = input_tokens + output_tokens
    return TokenUsage(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=total,
        provider=provider,
        model=model,
    )


def safe_pydantic_ai_usage(result: object, *, provider: str | None = None, model: str | None = None) -> TokenUsage:
    """Extract TokenUsage from a pydantic-ai run result, tolerating missing usage().

    Real ``AgentRunResult`` objects expose ``.usage()``; test doubles often don't. This helper
    treats any missing attribute or call failure as "no usage recorded" rather than crashing.
    """
    usage_attr = getattr(result, "usage", None)
    if usage_attr is None:
        return TokenUsage(provider=provider, model=model)
    usage_value: object
    if callable(usage_attr):
        try:
            usage_value = usage_attr()
        except Exception:  # noqa: BLE001 - test doubles or upstream renames must not crash trace persistence
            return TokenUsage(provider=provider, model=model)
    else:
        usage_value = usage_attr
    return from_pydantic_ai_usage(usage_value, provider=provider, model=model)


def merge(a: TokenUsage, b: TokenUsage) -> TokenUsage:
    """Add two TokenUsage values. Provider/model are kept from `a` if set, else from `b`."""
    return TokenUsage(
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
        total_tokens=a.total_tokens + b.total_tokens,
        provider=a.provider or b.provider,
        model=a.model or b.model,
    )


def total(role_usage: RoleUsage) -> TokenUsage:
    """Sum usage across all roles."""
    accumulator = TokenUsage()
    for role in ROLES:
        accumulator = merge(accumulator, getattr(role_usage, role))
    return accumulator


def _coerce_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _get_int_attr(obj: object, names: tuple[str, ...]) -> int:
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return _coerce_int(value)
    return 0
