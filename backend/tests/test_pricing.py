from pathlib import Path

from rag_common.enums import PipelineRole
from rag_common.pricing import (
    DEFAULT_PRICING,
    ModelPrice,
    PricingResolver,
    estimate_cost,
    load_pricing_overrides,
    merge_pricing,
)
from rag_common.usage import TokenUsage


def test_estimate_cost_returns_zero_for_unknown_model() -> None:
    cost = estimate_cost("nonexistent/model", TokenUsage(prompt_tokens=1000), PipelineRole.GENERATOR)
    assert cost == 0.0


def test_estimate_cost_returns_zero_for_empty_usage() -> None:
    cost = estimate_cost("openai/gpt-4.1-mini", TokenUsage(), PipelineRole.GENERATOR)
    assert cost == 0.0


def test_estimate_cost_for_chat_role_combines_input_and_output() -> None:
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    cost = estimate_cost("openai/gpt-4.1-mini", usage, PipelineRole.GENERATOR)
    expected = (
        DEFAULT_PRICING["openai/gpt-4.1-mini"].input_per_mtok + DEFAULT_PRICING["openai/gpt-4.1-mini"].output_per_mtok
    )
    assert abs(cost - expected) < 1e-9


def test_estimate_cost_for_embedding_role_uses_embedding_rate() -> None:
    usage = TokenUsage(prompt_tokens=500_000, total_tokens=500_000)
    cost = estimate_cost("openai/text-embedding-3-small", usage, PipelineRole.EMBEDDING)
    expected = 0.5 * (DEFAULT_PRICING["openai/text-embedding-3-small"].embedding_per_mtok or 0.0)
    assert abs(cost - expected) < 1e-9


def test_estimate_cost_for_rerank_role_uses_search_unit_rate() -> None:
    usage = TokenUsage(prompt_tokens=0, total_tokens=0)
    # Even with zero usage, rerank charges a per-search-unit cost; but our estimate_cost
    # currently treats empty usage as 0. Use a non-empty TokenUsage to trigger the path.
    usage_with = TokenUsage(prompt_tokens=1)
    cost = estimate_cost("cohere/rerank-v3.5", usage_with, PipelineRole.RERANK)
    assert cost == DEFAULT_PRICING["cohere/rerank-v3.5"].rerank_per_search_unit
    assert estimate_cost("cohere/rerank-v3.5", usage, PipelineRole.RERANK) == 0.0


def test_estimate_cost_returns_zero_when_role_pricing_missing() -> None:
    usage = TokenUsage(prompt_tokens=1000)
    # gpt-4.1-mini has no embedding_per_mtok set, so embedding role should be free.
    cost = estimate_cost("openai/gpt-4.1-mini", usage, PipelineRole.EMBEDDING)
    assert cost == 0.0


def test_load_pricing_overrides_returns_empty_for_none_path() -> None:
    assert load_pricing_overrides(None) == {}


def test_load_pricing_overrides_returns_empty_for_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    assert load_pricing_overrides(missing) == {}


def test_load_pricing_overrides_parses_yaml(tmp_path: Path) -> None:
    override_file = tmp_path / "pricing.yaml"
    override_file.write_text(
        "openai/gpt-4.1-mini:\n  input_per_mtok: 1.0\n  output_per_mtok: 2.0\n"
        "openai/text-embedding-3-small:\n  embedding_per_mtok: 0.05\n",
        encoding="utf-8",
    )
    overrides = load_pricing_overrides(override_file)
    assert overrides["openai/gpt-4.1-mini"].input_per_mtok == 1.0
    assert overrides["openai/gpt-4.1-mini"].output_per_mtok == 2.0
    assert overrides["openai/text-embedding-3-small"].embedding_per_mtok == 0.05


def test_merge_pricing_overrides_default() -> None:
    overrides = {"openai/gpt-4.1-mini": ModelPrice(input_per_mtok=99.0, output_per_mtok=99.0)}
    merged = merge_pricing(overrides)
    assert merged["openai/gpt-4.1-mini"].input_per_mtok == 99.0
    # Other defaults retained
    assert "openai/text-embedding-3-small" in merged


def test_pricing_resolver_estimate_uses_table() -> None:
    resolver = PricingResolver(table={"custom/model": ModelPrice(input_per_mtok=10.0, output_per_mtok=20.0)})
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000)
    cost = resolver.estimate("custom/model", usage, PipelineRole.GENERATOR)
    assert abs(cost - (10.0 + 10.0)) < 1e-9
