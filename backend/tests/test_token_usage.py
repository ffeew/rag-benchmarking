from types import SimpleNamespace

from rag_common.usage import (
    RoleUsage,
    TokenUsage,
    from_openrouter_usage,
    from_pydantic_ai_usage,
    merge,
    safe_pydantic_ai_usage,
    total,
)


def test_token_usage_is_empty_for_default() -> None:
    assert TokenUsage().is_empty() is True


def test_token_usage_is_not_empty_when_total_set() -> None:
    assert TokenUsage(total_tokens=10).is_empty() is False


def test_from_openrouter_usage_parses_standard_fields() -> None:
    raw = {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}
    usage = from_openrouter_usage(raw, provider="openrouter", model="m1")
    assert usage.prompt_tokens == 12
    assert usage.completion_tokens == 34
    assert usage.total_tokens == 46
    assert usage.provider == "openrouter"
    assert usage.model == "m1"


def test_from_openrouter_usage_handles_missing_total() -> None:
    usage = from_openrouter_usage({"prompt_tokens": 5, "completion_tokens": 7})
    assert usage.total_tokens == 12


def test_from_openrouter_usage_handles_empty_input() -> None:
    assert from_openrouter_usage(None).is_empty()
    assert from_openrouter_usage({}).is_empty()


def test_from_pydantic_ai_usage_reads_input_output_tokens() -> None:
    usage_obj = SimpleNamespace(input_tokens=8, output_tokens=4, total_tokens=12)
    usage = from_pydantic_ai_usage(usage_obj, provider="openrouter", model="m2")
    assert usage.prompt_tokens == 8
    assert usage.completion_tokens == 4
    assert usage.total_tokens == 12
    assert usage.model == "m2"


def test_from_pydantic_ai_usage_falls_back_when_total_missing() -> None:
    usage_obj = SimpleNamespace(input_tokens=2, output_tokens=3)
    usage = from_pydantic_ai_usage(usage_obj)
    assert usage.total_tokens == 5


def test_safe_pydantic_ai_usage_handles_missing_attribute() -> None:
    result = SimpleNamespace(output="hello")
    assert safe_pydantic_ai_usage(result).is_empty()


def test_safe_pydantic_ai_usage_handles_exception_in_call() -> None:
    def boom() -> object:
        raise RuntimeError("boom")

    result = SimpleNamespace(usage=boom)
    assert safe_pydantic_ai_usage(result).is_empty()


def test_safe_pydantic_ai_usage_reads_callable_usage() -> None:
    usage_obj = SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15)
    result = SimpleNamespace(usage=lambda: usage_obj)
    usage = safe_pydantic_ai_usage(result, provider="openrouter", model="m3")
    assert usage.total_tokens == 15
    assert usage.model == "m3"


def test_merge_sums_token_counts() -> None:
    a = TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3, model="m")
    b = TokenUsage(prompt_tokens=4, completion_tokens=5, total_tokens=9)
    merged = merge(a, b)
    assert merged.prompt_tokens == 5
    assert merged.completion_tokens == 7
    assert merged.total_tokens == 12
    assert merged.model == "m"


def test_total_sums_all_roles() -> None:
    role_usage = RoleUsage(
        planner=TokenUsage(total_tokens=1),
        verifier=TokenUsage(total_tokens=2),
        generator=TokenUsage(total_tokens=3),
        embedding=TokenUsage(total_tokens=4),
        rerank=TokenUsage(total_tokens=5),
        judge=TokenUsage(total_tokens=6),
    )
    assert total(role_usage).total_tokens == 21
