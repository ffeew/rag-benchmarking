"""Tests for the answer-text LLM judge.

The judge takes a (statement, answer) pair and asks an LLM to score whether
the answer asserts the statement, using a binary rubric. These tests mock
the OpenAI-compatible chat client so we exercise prompt assembly, response
parsing, and error handling without touching a real LLM.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from rag_evaluation.judge import JudgeVerdict, TextJudge, _parse_verdict


def _mock_client(content: str) -> MagicMock:
    """Build a mock OpenAI-compatible client that returns ``content`` once."""
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )
    return client


def test_parse_verdict_clean_json_binary_one() -> None:
    score, rationale = _parse_verdict('{"score": 1.0, "rationale": "Answer asserts the claim."}')
    assert score == 1.0
    assert rationale == "Answer asserts the claim."


def test_parse_verdict_clean_json_binary_zero() -> None:
    score, rationale = _parse_verdict('{"score": 0.0, "rationale": "Claim is absent."}')
    assert score == 0.0


def test_parse_verdict_strips_markdown_fences() -> None:
    score, rationale = _parse_verdict('```json\n{"score": 1.0, "rationale": "ok"}\n```')
    assert score == 1.0
    assert rationale == "ok"


def test_parse_verdict_extracts_embedded_object() -> None:
    score, rationale = _parse_verdict('Here is the verdict: {"score": 0.0, "rationale": "missing"}.')
    assert score == 0.0
    assert rationale == "missing"


def test_parse_verdict_coerces_non_binary_to_nearest() -> None:
    # The rubric is binary; a model returning 0.7 should round up so the
    # pass rate doesn't silently shift away from the gated thresholds.
    score, _ = _parse_verdict('{"score": 0.7, "rationale": "hedged"}')
    assert score == 1.0
    score, _ = _parse_verdict('{"score": 0.3, "rationale": "weakly present"}')
    assert score == 0.0


def test_parse_verdict_handles_malformed_response() -> None:
    score, rationale = _parse_verdict("model returned nothing parseable")
    assert score == 0.0
    assert rationale.startswith("parse_error:")


def test_parse_verdict_handles_missing_score() -> None:
    score, rationale = _parse_verdict('{"rationale": "no score field"}')
    assert score == 0.0
    assert rationale.startswith("invalid_score:")


def test_text_judge_passes_statement_and_answer_to_client() -> None:
    client = _mock_client('{"score": 1.0, "rationale": "yes"}')
    judge = TextJudge(client=client, model="glm-judge-test", temperature_zero=True)
    verdict = judge.judge(statement="Revenue grew year over year.", answer="Revenue increased by 12% YoY.")
    assert verdict == JudgeVerdict(score=1.0, rationale="yes", judge_model="glm-judge-test")
    create_kwargs = client.chat.completions.create.call_args.kwargs
    assert create_kwargs["model"] == "glm-judge-test"
    assert create_kwargs["temperature"] == 0.0
    assert create_kwargs["response_format"] == {"type": "json_object"}
    messages = create_kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert "binary" in messages[0]["content"].lower()
    assert "Revenue grew year over year." in messages[1]["content"]
    assert "Revenue increased by 12% YoY." in messages[1]["content"]


def test_text_judge_returns_judge_error_on_client_exception() -> None:
    # A flaky judge must not abort the per-case loop. The verdict is recorded
    # with a clear rationale so an analyst grepping ``judge_error:`` in the
    # artifact can spot how many cases lost their LLM verdict.
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("connection refused")
    judge = TextJudge(client=client, model="glm-judge-test")
    verdict = judge.judge(statement="anything", answer="anything")
    assert verdict.score == 0.0
    assert verdict.rationale == "judge_error: RuntimeError"
    assert verdict.judge_model == "glm-judge-test"


def test_text_judge_skips_temperature_when_disabled() -> None:
    client = _mock_client('{"score": 0.0, "rationale": "no"}')
    judge = TextJudge(client=client, model="glm", temperature_zero=False)
    judge.judge(statement="x", answer="y")
    create_kwargs = client.chat.completions.create.call_args.kwargs
    assert "temperature" not in create_kwargs
