from rag_common.db import models
from rag_evaluation_worker.runner import aggregate_metrics
from rag_evaluation_worker.scoring import answer_declined_to_respond, bootstrap_mean_ci, score_answer


def test_score_answer_numeric_tolerance() -> None:
    metrics = score_answer(
        answer="Revenue was $94.1 billion.",
        insufficiency_reason=None,
        raw_spec={
            "answer_type": "numeric",
            "expected_values": [
                {
                    "label": "revenue",
                    "value_numeric": 94.0,
                    "unit": "billion",
                    "tolerance_abs": 0.2,
                }
            ],
        },
    )
    assert metrics["answer_scoreable"] is True
    assert metrics["answer_accuracy"] == 1.0


def test_score_answer_insufficient_requires_state_and_keywords() -> None:
    metrics = score_answer(
        answer="The filings contain insufficient evidence for country-level headcount.",
        insufficiency_reason="Country-level employees were not disclosed.",
        raw_spec={
            "answer_type": "insufficient",
            "required_reason_keywords": ["insufficient", "not disclosed"],
        },
    )
    assert metrics["answer_accuracy"] == 1.0
    assert metrics["insufficient_correct"] == 1.0


def test_bootstrap_mean_ci_is_deterministic() -> None:
    first = bootstrap_mean_ci([0.0, 1.0, 1.0], seed=7, samples=50)
    second = bootstrap_mean_ci([0.0, 1.0, 1.0], seed=7, samples=50)
    assert first == second


def test_aggregate_separates_scientific_from_diagnostic_cases() -> None:
    results = [
        models.EvalResult(
            eval_run_id="run",
            retrieval_mode="full_agentic",
            metrics={
                "gold_eligible": True,
                "answer_gold_eligible": True,
                "answer_accuracy": 1.0,
                "verification_status": "verified",
                "category": "table_lookup",
                "difficulty": "easy",
                "tags": ["table"],
            },
        ),
        models.EvalResult(
            eval_run_id="run",
            retrieval_mode="full_agentic",
            metrics={
                "gold_eligible": False,
                "answer_gold_eligible": False,
                "answer_accuracy": None,
                "verification_status": "draft",
                "category": "table_lookup",
                "difficulty": "easy",
                "tags": ["table"],
            },
        ),
    ]
    aggregate = aggregate_metrics(results)
    mode = aggregate["full_agentic"]
    assert mode["diagnostic_case_count"] == 2
    assert mode["scientific_case_count"] == 1
    assert mode["answer_accuracy_rate"] == 1.0
    assert mode["by_category"]["table_lookup"]["scientific_case_count"] == 1


def test_answer_declined_to_respond_catches_insufficiency_phrases() -> None:
    assert answer_declined_to_respond("The dataset does not contain enough evidence.", None) is True


def test_answer_declined_to_respond_catches_refusal_phrases() -> None:
    assert answer_declined_to_respond("I cannot provide the requested figure.", None) is True


def test_answer_declined_to_respond_is_false_for_substantive_answers() -> None:
    assert (
        answer_declined_to_respond(
            "Total net sales were $416,161 million [AAPL 2025-10-31 10-K, p. 71].",
            None,
        )
        is False
    )


def _scoreable_result(*, retrieval_mode: str, passed: bool, **overrides: object) -> models.EvalResult:
    metrics = {
        "gold_eligible": True,
        "answer_gold_eligible": True,
        "evidence_gold_eligible": False,
        "answer_accuracy": 1.0 if passed else 0.0,
        "citation_validity": 1.0,
        "recall_at_5": 1.0,
        "verification_status": "verified",
        "category": "single_company_lookup",
        "difficulty": "easy",
        "tags": ["revenue"],
        "passed": passed,
        "latency_ms": 12000,
    }
    metrics.update(overrides)
    return models.EvalResult(
        eval_run_id="run",
        retrieval_mode=retrieval_mode,
        variant_name=retrieval_mode,
        metrics=metrics,
    )


def test_aggregate_metrics_emits_pass_rate_top_level_and_per_variant() -> None:
    results = [
        _scoreable_result(retrieval_mode="full_agentic", passed=True),
        _scoreable_result(retrieval_mode="full_agentic", passed=False, answer_accuracy=0.0),
        _scoreable_result(retrieval_mode="llm_only", passed=True),
    ]
    aggregate = aggregate_metrics(results)
    assert aggregate["pass_rate"] == 2 / 3
    assert aggregate["pass_count"] == 2
    assert aggregate["pass_eligible_count"] == 3
    assert aggregate["full_agentic"]["pass_rate"] == 0.5
    assert aggregate["full_agentic"]["pass_count"] == 1
    assert aggregate["llm_only"]["pass_rate"] == 1.0


def test_aggregate_metrics_top_level_includes_avg_latency_ms() -> None:
    results = [
        _scoreable_result(retrieval_mode="full_agentic", passed=True, latency_ms=10000),
        _scoreable_result(retrieval_mode="single_pass", passed=True, latency_ms=20000),
    ]
    aggregate = aggregate_metrics(results)
    assert aggregate["avg_latency_ms"] == 15000.0
