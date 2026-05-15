from rag_common.db import models
from rag_evaluation_worker.runner import aggregate_metrics
from rag_evaluation_worker.scoring import bootstrap_mean_ci, score_answer


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
