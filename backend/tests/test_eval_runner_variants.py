"""Tests for the variant-spec wiring in the eval runner.

Verifies that variant specs are materialized correctly, overrides reach
``run_query`` as a cloned ``Settings``, and that ``variant_name`` /
``overrides_applied`` land on every persisted ``EvalResult``.
"""

from typing import Any

import pytest
from rag_common.config import Settings
from rag_common.db import models
from rag_common.schemas import QueryResponse
from rag_evaluation_worker.runner import _detect_pairing_skew, _resolve_variants
from sqlalchemy.orm import Session


def test_resolve_variants_reads_new_shape() -> None:
    run_config = {
        "variants": [
            {"name": "a", "retrieval_mode": "full_agentic", "overrides": {"hyde_enabled": False}},
            {"name": "b", "retrieval_mode": "single_pass", "overrides": {}},
        ],
    }
    specs = _resolve_variants(run_config)
    assert [s.name for s in specs] == ["a", "b"]
    assert specs[0].overrides.hyde_enabled is False
    assert specs[1].overrides.hyde_enabled is None


def test_resolve_variants_falls_back_to_system_variants() -> None:
    run_config = {"system_variants": ["full_agentic", "llm_only"]}
    specs = _resolve_variants(run_config)
    assert [s.name for s in specs] == ["full_agentic", "llm_only"]
    assert all(s.overrides.model_dump(exclude_none=True) == {} for s in specs)


def test_resolve_variants_default_when_empty() -> None:
    specs = _resolve_variants({})
    assert [s.name for s in specs] == ["full_agentic", "single_pass", "llm_only"]


def test_resolve_variants_rejects_malformed_list() -> None:
    import pytest as pytest_module  # local import; keeps the typing block clean

    with pytest_module.raises(ValueError, match="must be a list"):
        _resolve_variants({"variants": "not-a-list"})


def test_detect_pairing_skew_balanced() -> None:
    expected = {"c1", "c2", "c3"}
    case_ids_per_variant: dict[str, set[str]] = {
        "full_agentic": set(expected),
        "single_pass": set(expected),
    }
    report = _detect_pairing_skew(case_ids_per_variant, expected_cases=expected)
    assert report["balanced"] is True
    assert report["missing"] == {}
    assert report["expected_case_count"] == 3


def test_detect_pairing_skew_flags_missing() -> None:
    expected = {"c1", "c2", "c3"}
    case_ids_per_variant: dict[str, set[str]] = {
        "full_agentic": {"c1", "c2", "c3"},
        "single_pass": {"c1", "c3"},
    }
    report = _detect_pairing_skew(case_ids_per_variant, expected_cases=expected)
    assert report["balanced"] is False
    assert report["missing"] == {"single_pass": ["c2"]}


def _stub_query_response(trace_id: str) -> QueryResponse:
    return QueryResponse(
        answer="42",
        citations=[],
        evidence=[],
        trace_id=trace_id,
        confidence=0.5,
    )


def test_runner_passes_overridden_settings_to_run_query(
    db_session: Session,
    seed_dataset: models.Dataset,
    seed_eval_case: models.EvalCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: persist a 2-variant EvalRun, run, assert that the second
    variant's ``hyde_enabled=False`` reached run_query as a cloned Settings."""

    eval_run = models.EvalRun(
        dataset_id=seed_dataset.id,
        status="queued",
        run_config={
            "case_ids": [seed_eval_case.id],
            "variants": [
                {"name": "full_agentic", "retrieval_mode": "full_agentic", "overrides": {}},
                {
                    "name": "full_agentic_no_hyde",
                    "retrieval_mode": "full_agentic",
                    "overrides": {"hyde_enabled": False},
                },
            ],
            "benchmark_profile": "diagnostic",  # skip the scientific-gold gate
            "bootstrap_seed": 1729,
        },
        system_variant="full_agentic,full_agentic_no_hyde",
        model_metadata={},
    )
    db_session.add(eval_run)
    db_session.commit()
    db_session.refresh(eval_run)

    # Seed two QueryTrace rows so the FK on EvalResult.trace_id is satisfied.
    trace_ids = ["trace-fa", "trace-fa-no-hyde"]
    for tid in trace_ids:
        db_session.add(
            models.QueryTrace(
                id=tid,
                dataset_id=seed_dataset.id,
                user_question="seed",
                retrieval_mode="full_agentic",
            )
        )
    db_session.commit()
    trace_iter = iter(trace_ids)

    captured: list[dict[str, Any]] = []

    def fake_run_query(_session: Any, *, request: Any, settings: Settings) -> QueryResponse:  # noqa: ARG001
        captured.append({"retrieval_mode": request.retrieval_mode, "hyde_enabled": settings.hyde_enabled})
        return _stub_query_response(next(trace_iter))

    from rag_evaluation_worker import runner as runner_module

    monkeypatch.setattr(runner_module, "run_query", fake_run_query)
    # Skip RAGAS in this test.
    monkeypatch.setattr(runner_module, "_attach_ragas_scores", lambda *a, **k: {})
    # Skip the parser/chunk diagnostics, which require ingestion artifacts.
    monkeypatch.setattr(runner_module, "_ingestion_diagnostics", lambda session, dataset_id: {})
    # Also bypass commit_job_progress (talks to Redis).
    monkeypatch.setattr(runner_module, "commit_job_progress", lambda *a, **k: None)

    runner_module.run_evaluation(db_session, eval_run_id=eval_run.id, job_id=None)
    db_session.commit()

    assert captured == [
        {"retrieval_mode": "full_agentic", "hyde_enabled": True},
        {"retrieval_mode": "full_agentic", "hyde_enabled": False},
    ]

    results = list(db_session.query(models.EvalResult).filter_by(eval_run_id=eval_run.id))
    assert {r.variant_name for r in results} == {"full_agentic", "full_agentic_no_hyde"}
    # Each row carries variant_name + overrides_applied on the persisted metrics blob.
    for row in results:
        assert row.variant_name in {"full_agentic", "full_agentic_no_hyde"}
        assert row.metrics.get("variant_name") == row.variant_name
        if row.variant_name == "full_agentic_no_hyde":
            assert row.metrics.get("overrides_applied") == {"hyde_enabled": False}

    # And the aggregate bucketed on variant_name.
    db_session.refresh(eval_run)
    assert "full_agentic" in eval_run.metrics
    assert "full_agentic_no_hyde" in eval_run.metrics
    assert eval_run.metrics["pairing_skew"]["balanced"] is True
