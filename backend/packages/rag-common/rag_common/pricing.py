"""Provider pricing table and cost estimation."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml
from pydantic import BaseModel, Field, NonNegativeFloat

if TYPE_CHECKING:
    from rag_common.usage import Role, TokenUsage


class ModelPrice(BaseModel):
    """USD pricing for one model. All fields default to 0 / None and are non-negative."""

    input_per_mtok: NonNegativeFloat = 0.0
    output_per_mtok: NonNegativeFloat = 0.0
    embedding_per_mtok: NonNegativeFloat | None = None
    rerank_per_search_unit: NonNegativeFloat | None = None


DEFAULT_PRICING: dict[str, ModelPrice] = {
    "openai/gpt-4.1-mini": ModelPrice(input_per_mtok=0.40, output_per_mtok=1.60),
    "openai/gpt-4o-mini": ModelPrice(input_per_mtok=0.15, output_per_mtok=0.60),
    "openai/gpt-4o": ModelPrice(input_per_mtok=2.50, output_per_mtok=10.00),
    "anthropic/claude-haiku-4.5": ModelPrice(input_per_mtok=1.00, output_per_mtok=5.00),
    "anthropic/claude-sonnet-4.6": ModelPrice(input_per_mtok=3.00, output_per_mtok=15.00),
    "anthropic/claude-opus-4.7": ModelPrice(input_per_mtok=15.00, output_per_mtok=75.00),
    "openai/text-embedding-3-small": ModelPrice(embedding_per_mtok=0.02),
    "openai/text-embedding-3-large": ModelPrice(embedding_per_mtok=0.13),
    "cohere/embed-english-v3.0": ModelPrice(embedding_per_mtok=0.10),
    "cohere/rerank-v3.5": ModelPrice(rerank_per_search_unit=0.002),
    "cohere/rerank-english-v3.0": ModelPrice(rerank_per_search_unit=0.002),
}


def estimate_cost(model: str | None, usage: TokenUsage, role: Role) -> float:
    """Estimate USD cost for a single provider call given the model, usage, and role.

    Returns 0.0 when the model is unknown so unrecognised models don't silently inflate totals;
    operators can supply an overrides YAML to fill gaps.
    """
    if not model or usage.is_empty():
        return 0.0
    price = DEFAULT_PRICING.get(model)
    if price is None:
        return 0.0
    if role == "embedding":
        if price.embedding_per_mtok is None:
            return 0.0
        return _per_mtok(price.embedding_per_mtok, usage.total_tokens or usage.prompt_tokens)
    if role == "rerank":
        if price.rerank_per_search_unit is None:
            return 0.0
        return float(price.rerank_per_search_unit)
    input_cost = _per_mtok(price.input_per_mtok, usage.prompt_tokens)
    output_cost = _per_mtok(price.output_per_mtok, usage.completion_tokens)
    return input_cost + output_cost


def load_pricing_overrides(path: Path | None) -> dict[str, ModelPrice]:
    """Load a YAML pricing overrides file. Returns {} if path is None or missing.

    YAML schema is identical to DEFAULT_PRICING:

        openai/gpt-4o-mini:
          input_per_mtok: 0.15
          output_per_mtok: 0.60
    """
    if path is None:
        return {}
    file = Path(path)
    if not file.exists():
        return {}
    with file.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Pricing overrides at {file} must be a mapping, got {type(raw).__name__}")
    overrides: dict[str, ModelPrice] = {}
    for model_name, fields in raw.items():
        if not isinstance(fields, dict):
            raise ValueError(f"Pricing override for {model_name!r} must be a mapping")
        overrides[str(model_name)] = ModelPrice(**cast("dict[str, object]", fields))
    return overrides


def merge_pricing(overrides: dict[str, ModelPrice]) -> dict[str, ModelPrice]:
    """Apply overrides on top of DEFAULT_PRICING. Override entries replace defaults wholesale."""
    merged = dict(DEFAULT_PRICING)
    merged.update(overrides)
    return merged


class PricingResolver(BaseModel):
    """Bundle of resolved pricing data — pass to estimate_cost variants that accept overrides."""

    table: dict[str, ModelPrice] = Field(default_factory=lambda: dict(DEFAULT_PRICING))

    def estimate(self, model: str | None, usage: TokenUsage, role: Role) -> float:
        if not model or usage.is_empty():
            return 0.0
        price = self.table.get(model)
        if price is None:
            return 0.0
        if role == "embedding":
            if price.embedding_per_mtok is None:
                return 0.0
            return _per_mtok(price.embedding_per_mtok, usage.total_tokens or usage.prompt_tokens)
        if role == "rerank":
            if price.rerank_per_search_unit is None:
                return 0.0
            return float(price.rerank_per_search_unit)
        return _per_mtok(price.input_per_mtok, usage.prompt_tokens) + _per_mtok(
            price.output_per_mtok, usage.completion_tokens
        )


def _per_mtok(price_per_mtok: float, tokens: int) -> float:
    if tokens <= 0 or price_per_mtok <= 0:
        return 0.0
    return (tokens / 1_000_000.0) * price_per_mtok
