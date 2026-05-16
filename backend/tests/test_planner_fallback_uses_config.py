"""Deterministic-planner verifications that domain config flows through.

``infer_query_plan`` is the heuristic fallback used when the chat agent is unavailable.
It used to hard-code SEC ``VALID_FORMS`` and ``METRIC_TERMS`` constants; after the
abstraction it must consult ``DatasetConfig`` for both so non-SEC corpora are not
mis-classified into 10-K / 10-Q / 8-K shapes.
"""

from __future__ import annotations

from rag_common.schemas import QueryFilters
from rag_retrieval.dataset_config import DatasetConfig
from rag_retrieval.planning import infer_query_plan


def _config(
    *,
    valid_forms: tuple[str, ...],
    metric_terms: tuple[str, ...] = (),
    known_tickers: frozenset[str] = frozenset(),
) -> DatasetConfig:
    return DatasetConfig(
        id="d-cfg",
        name="custom",
        description=None,
        domain_label="Custom corpus",
        entity_label="subject",
        valid_forms=valid_forms,
        metric_terms=metric_terms,
        hyde_style_hint=None,
        citation_label_template="[{entity} {filing_date} {form_type}, p. {page}]",
        known_tickers=known_tickers,
    )


def test_infer_query_plan_uses_custom_valid_forms_not_sec_defaults() -> None:
    config = _config(
        valid_forms=("MEMO", "INCIDENT"),
        metric_terms=(),
        known_tickers=frozenset(),
    )

    plan = infer_query_plan(
        question="Show the latest MEMO about routing changes.",
        filters=QueryFilters(),
        dataset_config=config,
    )

    assert plan.forms == ["MEMO"]
    assert plan.latest is True
    # SEC forms must not appear when the dataset's valid_forms restricts to MEMO/INCIDENT.
    assert "10-K" not in plan.forms
    assert "10-Q" not in plan.forms


def test_infer_query_plan_only_uses_forms_mentioned_in_question() -> None:
    """When the question references multiple dataset-known forms, the plan keeps them all."""
    config = _config(
        valid_forms=("MEMO", "INCIDENT"),
        metric_terms=(),
        known_tickers=frozenset(),
    )

    plan = infer_query_plan(
        question="Compare MEMO and INCIDENT counts by quarter.",
        filters=QueryFilters(),
        dataset_config=config,
    )

    assert set(plan.forms) == {"MEMO", "INCIDENT"}
    assert plan.query_type == "comparison"


def test_infer_query_plan_extracts_metric_hints_from_dataset_terms() -> None:
    config = _config(
        valid_forms=("MEMO",),
        metric_terms=("incident", "escalation", "control"),
    )

    plan = infer_query_plan(
        question="Summarize incident escalation patterns this quarter.",
        filters=QueryFilters(),
        dataset_config=config,
    )

    # The heuristic extracts metric terms that literally appear in the question.
    assert "incident" in plan.metrics
    assert "escalation" in plan.metrics
    assert "control" not in plan.metrics


def test_infer_query_plan_backcompat_with_known_tickers_argument() -> None:
    """The legacy ``known_tickers=`` arg should still work without a DatasetConfig.

    Existing tests / call sites pass known_tickers directly; the abstraction must keep
    that path green by synthesizing a SEC-flavored DatasetConfig internally.
    """
    plan = infer_query_plan(
        question="What is TSLA latest 10-K debt?",
        filters=QueryFilters(),
        known_tickers={"TSLA"},
    )

    assert plan.target_tickers == ["TSLA"]
    assert plan.forms == ["10-K"]
    assert plan.latest is True
    # Default SEC config carries METRIC_TERMS containing "debt".
    assert "debt" in plan.metrics
