"""Unit tests for DatasetConfig resolution."""

from types import SimpleNamespace
from typing import cast

import pytest
from rag_retrieval.dataset_config import (
    DEFAULT_CITATION_LABEL_TEMPLATE,
    DEFAULT_METRIC_TERMS,
    DEFAULT_VALID_FORMS,
    DatasetConfig,
    format_citation,
    load_dataset_config,
)


def _stub_session(dataset_row: object, tickers: list[str]) -> object:
    """Stub a SQLAlchemy session that surfaces a single dataset row and ticker list."""
    return SimpleNamespace(
        get=lambda _model, _id: dataset_row,
        scalars=lambda _stmt: iter(tickers),
    )


def test_default_sec_returns_sec_flavored_defaults() -> None:
    config = DatasetConfig.default_sec(known_tickers=frozenset({"AAPL", "MSFT"}))

    assert config.domain_label == "SEC filings of US public companies"
    assert config.entity_label == "ticker"
    assert config.valid_forms == DEFAULT_VALID_FORMS
    assert config.metric_terms == DEFAULT_METRIC_TERMS
    assert config.hyde_style_hint is None
    assert config.citation_label_template == DEFAULT_CITATION_LABEL_TEMPLATE
    assert config.known_tickers == frozenset({"AAPL", "MSFT"})


def test_load_dataset_config_resolves_null_columns_to_sec_defaults() -> None:
    """A dataset row with every override left null should yield the SEC defaults."""
    dataset_row = SimpleNamespace(
        id="d1",
        name="sec-filings",
        description="default",
        domain_label=None,
        entity_label=None,
        valid_forms=None,
        metric_terms=None,
        hyde_style_hint=None,
        citation_label_template=None,
    )
    session = _stub_session(dataset_row, ["aapl", "msft"])

    config = load_dataset_config(session, "d1")  # type: ignore[arg-type]

    assert config.id == "d1"
    assert config.domain_label == "SEC filings of US public companies"
    assert config.entity_label == "ticker"
    assert config.valid_forms == DEFAULT_VALID_FORMS
    assert config.metric_terms == DEFAULT_METRIC_TERMS
    assert config.citation_label_template == DEFAULT_CITATION_LABEL_TEMPLATE
    # known_tickers are upper-cased so the planner / retrieval agent see a single
    # canonical form regardless of casing in the underlying corpus.
    assert config.known_tickers == frozenset({"AAPL", "MSFT"})


def test_load_dataset_config_honors_explicit_overrides() -> None:
    """Populated override columns flow through verbatim - no SEC fallback leakage."""
    dataset_row = SimpleNamespace(
        id="d2",
        name="compliance-memos",
        description="Internal compliance memos for a non-SEC corpus.",
        domain_label="Internal compliance memos",
        entity_label="subject",
        valid_forms=["MEMO", "INCIDENT"],
        metric_terms=["incident", "escalation", "control"],
        hyde_style_hint="Compliance memo register: incident description, remediation, control mapping.",
        citation_label_template="[{entity}/{filing_date}/{form_type}#p{page}]",
    )
    session = _stub_session(dataset_row, ["TEAM_A"])

    config = load_dataset_config(session, "d2")  # type: ignore[arg-type]

    assert config.domain_label == "Internal compliance memos"
    assert config.entity_label == "subject"
    assert config.valid_forms == ("MEMO", "INCIDENT")
    assert config.metric_terms == ("incident", "escalation", "control")
    assert "Compliance memo register" in (config.hyde_style_hint or "")
    assert config.citation_label_template == "[{entity}/{filing_date}/{form_type}#p{page}]"
    assert config.known_tickers == frozenset({"TEAM_A"})


def test_load_dataset_config_falls_back_when_jsonb_column_is_empty_list() -> None:
    """Empty arrays mean "not configured" - resolver should still return SEC defaults."""
    dataset_row = SimpleNamespace(
        id="d3",
        name="sparse",
        description=None,
        domain_label=None,
        entity_label=None,
        valid_forms=[],
        metric_terms=[],
        hyde_style_hint="",
        citation_label_template="",
    )
    session = _stub_session(dataset_row, [])

    config = load_dataset_config(session, "d3")  # type: ignore[arg-type]

    assert config.valid_forms == DEFAULT_VALID_FORMS
    assert config.metric_terms == DEFAULT_METRIC_TERMS
    assert config.citation_label_template == DEFAULT_CITATION_LABEL_TEMPLATE
    # Empty hyde_style_hint string resolves to None (no STYLE_HINT line emitted).
    assert config.hyde_style_hint is None


def test_load_dataset_config_raises_when_dataset_missing() -> None:
    session = cast("object", SimpleNamespace(get=lambda _m, _i: None, scalars=lambda _s: iter([])))

    with pytest.raises(ValueError, match="not found"):
        load_dataset_config(session, "nope")  # type: ignore[arg-type]


def test_format_citation_uses_default_template_with_isoformat_dates() -> None:
    from datetime import date

    label = format_citation(entity="AAPL", filing_date=date(2025, 1, 31), form_type="10-K", page=23)

    assert label == "[AAPL 2025-01-31 10-K, p. 23]"


def test_format_citation_handles_undated_evidence() -> None:
    label = format_citation(entity="AAPL", filing_date=None, form_type="10-K", page=23)

    assert label == "[AAPL undated 10-K, p. 23]"


def test_format_citation_renders_custom_template() -> None:
    """A dataset can override the citation shape for non-SEC corpora."""
    label = format_citation(
        entity="case-1234",
        filing_date="2024-06-10",
        form_type="MEMO",
        page=7,
        template="{entity}/{filing_date}/{form_type}#p{page}",
    )

    assert label == "case-1234/2024-06-10/MEMO#p7"
