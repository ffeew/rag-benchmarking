from rag_common.db import models
from rag_common.eval_aggregation import aggregate_metrics, bootstrap_mean_ci
from rag_evaluation.judge import JudgeVerdict
from rag_evaluation.scoring import answer_declined_to_respond, score_answer


class _StubJudge:
    """Deterministic stand-in for ``TextJudge`` so scoring tests don't touch an LLM.

    Returns the verdict mapped from ``statement`` if present, otherwise a 0.0
    verdict so a missing mapping looks like a "claim absent" call rather than
    silently passing.
    """

    def __init__(self, verdicts: dict[str, JudgeVerdict]) -> None:
        self._verdicts = verdicts
        self.calls: list[tuple[str, str]] = []

    def judge(self, *, statement: str, answer: str) -> JudgeVerdict:
        self.calls.append((statement, answer))
        return self._verdicts.get(
            statement, JudgeVerdict(score=0.0, rationale="unmapped", judge_model="stub")
        )


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
    assert answer_declined_to_respond("The dataset does not contain enough evidence.") is True


def test_answer_declined_to_respond_catches_refusal_phrases() -> None:
    assert answer_declined_to_respond("I cannot provide the requested figure.") is True


def test_answer_declined_to_respond_is_false_for_substantive_answers() -> None:
    assert (
        answer_declined_to_respond(
            "Total net sales were $416,161 million [AAPL 2025-10-31 10-K, p. 71].",
        )
        is False
    )


def test_answer_declined_to_respond_ignores_upstream_pipeline_signal() -> None:
    # Regression: the helper used to accept ``insufficiency_reason`` and merge
    # it into the keyword scan, so a correctly-answered case could be flagged
    # ``insufficient=1.0`` whenever the upstream generator left a hedge note
    # mentioning "does not contain" / "not enough evidence" / "insufficient".
    # The signature was tightened so only the rendered answer text votes here.
    correct_answer = (
        "Apple's total net sales for fiscal 2025 were $416,161 million "
        "[AAPL 2025-10-31 10-K, p. 70] [AAPL 2025-10-31 10-K, p. 71]."
    )
    assert answer_declined_to_respond(correct_answer) is False


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


def test_score_answer_text_value_uses_judge_when_provided() -> None:
    # The judge approves a paraphrase that the legacy substring path would have
    # missed — proves the judge is wired into the text-value scoring path and
    # the verdict's match_type / rationale surface in the result.
    judge = _StubJudge(
        {"Revenue grew year over year.": JudgeVerdict(score=1.0, rationale="paraphrase ok", judge_model="stub")}
    )
    metrics = score_answer(
        answer="Annual revenue rose meaningfully YoY.",
        insufficiency_reason=None,
        raw_spec={
            "answer_type": "text",
            "expected_values": [{"label": "yoy_growth", "value_text": "Revenue grew year over year."}],
        },
        judge=judge,
    )
    assert metrics["answer_accuracy"] == 1.0
    value_scores = metrics["value_scores"]
    assert value_scores[0]["match_type"] == "text_llm_judge"
    assert value_scores[0]["rationale"] == "paraphrase ok"
    assert value_scores[0]["judge_model"] == "stub"
    assert judge.calls == [("Revenue grew year over year.", "Annual revenue rose meaningfully YoY.")]


def test_score_answer_text_value_falls_back_to_substring_without_judge() -> None:
    # Existing behavior: with no judge, ``value_text`` keeps the lowercased
    # substring containment so offline scoring (tests, dry runs) stays
    # deterministic.
    metrics = score_answer(
        answer="Revenue grew year over year.",
        insufficiency_reason=None,
        raw_spec={
            "answer_type": "text",
            "expected_values": [{"label": "yoy", "value_text": "Revenue grew year over year."}],
        },
    )
    assert metrics["value_scores"][0]["match_type"] == "text_substring"
    assert metrics["answer_accuracy"] == 1.0


def test_score_answer_required_claims_use_judge_per_claim() -> None:
    judge = _StubJudge(
        {
            "Apple's iPhone is the largest product line.": JudgeVerdict(
                score=1.0, rationale="paraphrased", judge_model="stub"
            ),
            "Services revenue exceeded $100 billion.": JudgeVerdict(
                score=0.0, rationale="services figure not stated", judge_model="stub"
            ),
        }
    )
    metrics = score_answer(
        answer="iPhone dominates Apple's product lineup; Services is reported but no dollar figure given.",
        insufficiency_reason=None,
        raw_spec={
            "answer_type": "text",
            "expected_values": [],
            "required_claims": [
                "Apple's iPhone is the largest product line.",
                "Services revenue exceeded $100 billion.",
            ],
        },
        judge=judge,
    )
    assert metrics["required_claim_hit_rate"] == 0.5
    verdicts = metrics["required_claim_verdicts"]
    assert {v["claim"] for v in verdicts} == {
        "Apple's iPhone is the largest product line.",
        "Services revenue exceeded $100 billion.",
    }
    for verdict in verdicts:
        assert verdict["match_type"] == "text_llm_judge"
        assert "rationale" in verdict


def test_score_answer_numeric_path_skips_judge_entirely() -> None:
    # Numeric scoring is regex + tolerance — it must not consult the judge
    # even when one is supplied, because adding LLM latency for an already
    # robust path would be wasted cost.
    judge = _StubJudge({})
    metrics = score_answer(
        answer="Revenue was $94.1 billion.",
        insufficiency_reason=None,
        raw_spec={
            "answer_type": "numeric",
            "expected_values": [
                {"label": "revenue", "value_numeric": 94.0, "unit": "billion", "tolerance_abs": 0.2}
            ],
        },
        judge=judge,
    )
    assert metrics["answer_accuracy"] == 1.0
    assert metrics["value_scores"][0]["match_type"] == "numeric"
    assert judge.calls == []


def test_aggregate_metrics_top_level_includes_avg_latency_ms() -> None:
    results = [
        _scoreable_result(retrieval_mode="full_agentic", passed=True, latency_ms=10000),
        _scoreable_result(retrieval_mode="single_pass", passed=True, latency_ms=20000),
    ]
    aggregate = aggregate_metrics(results)
    assert aggregate["avg_latency_ms"] == 15000.0
