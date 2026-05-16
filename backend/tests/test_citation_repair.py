"""Tests for the generator's citation-validator-driven retry behavior.

The generator agent now uses ``@agent.output_validator`` raising ``ModelRetry`` for
invalid citation tags - pydantic-ai performs the bounded repair turn internally. From
``generate_answer_with_agent``'s perspective there are three observable outcomes:

- run returns and ``usage.requests == 1`` -> first attempt passed (``citation_validation="passed"``)
- run returns and ``usage.requests > 1`` -> validator triggered a retry that succeeded (``"repaired"``)
- run raises ``UnexpectedModelBehavior`` -> retry budget exhausted -> extractive fallback
"""

from datetime import date
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from rag_common.config import Settings
from rag_retrieval import generation
from rag_retrieval.generation import GeneratorOutput, generate_answer_with_agent
from rag_retrieval.hybrid import RetrievedChunk


def _retrieved_chunk(chunk_id: str, ticker: str, text: str, page: int) -> RetrievedChunk:
    chunk = SimpleNamespace(id=chunk_id, text=text, page_start=page, contains_table=False)
    document = SimpleNamespace(
        ticker=ticker,
        filing_date=date(2025, 1, 31),
        form_type="10-K",
    )
    return cast(
        "RetrievedChunk",
        SimpleNamespace(
            chunk=chunk,
            document=document,
            score=0.9,
            semantic_rank=1,
            lexical_rank=None,
            rerank_score=None,
        ),
    )


def _settings() -> Settings:
    return cast(
        "Settings",
        SimpleNamespace(
            zai_chat_model="glm-4.7",
            allow_mock_providers=False,
        ),
    )


def _fake_result(output: GeneratorOutput, *, requests: int) -> object:
    """Build a result that quacks like ``AgentRunResult``: ``output`` + ``usage`` property."""
    return SimpleNamespace(
        output=output,
        usage=SimpleNamespace(requests=requests, input_tokens=0, output_tokens=0, total_tokens=0),
    )


def test_citation_repair_records_repaired_when_validator_triggers_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful run that took two requests means the validator ran one retry."""
    evidence = [_retrieved_chunk("c1", "AAPL", "Apple revenue was $394B in 2024.", 10)]

    def fake_run_sync(_prompt: str, *, deps: object) -> object:  # noqa: ARG001
        return _fake_result(
            GeneratorOutput(
                answer="Apple revenue was $394B ##e1.",
                citations_used=["##e1"],
                insufficiency_reason=None,
                confidence=0.85,
            ),
            requests=2,
        )

    monkeypatch.setattr(
        generation,
        "_generator_agent",
        lambda _settings: SimpleNamespace(run_sync=fake_run_sync),
    )

    answer, _ = generate_answer_with_agent(
        question="What was Apple's revenue?",
        evidence=evidence,
        plan=None,
        settings=_settings(),
    )

    assert answer.metadata["citation_validation"] == "repaired"
    assert answer.metadata["repair_used"] is True
    assert "[AAPL 2025-01-31 10-K, p. 10]" in answer.answer
    assert "##e1" not in answer.answer


def test_citation_validation_passes_on_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = [_retrieved_chunk("c1", "AAPL", "Apple revenue was $394B in 2024.", 10)]

    def fake_run_sync(_prompt: str, *, deps: object) -> object:  # noqa: ARG001
        return _fake_result(
            GeneratorOutput(
                answer="Apple revenue was $394B ##e1.",
                citations_used=["##e1"],
                insufficiency_reason=None,
                confidence=0.85,
            ),
            requests=1,
        )

    monkeypatch.setattr(
        generation,
        "_generator_agent",
        lambda _settings: SimpleNamespace(run_sync=fake_run_sync),
    )

    answer, _ = generate_answer_with_agent(
        question="What was Apple's revenue?",
        evidence=evidence,
        plan=None,
        settings=_settings(),
    )

    assert answer.metadata["citation_validation"] == "passed"
    assert answer.metadata["repair_used"] is False
    assert "[AAPL 2025-01-31 10-K, p. 10]" in answer.answer


def test_unrecoverable_validator_failure_falls_back_to_extractive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When pydantic-ai exhausts ``output_retries`` it raises UnexpectedModelBehavior."""
    evidence = [_retrieved_chunk("c1", "AAPL", "Apple revenue was $394B in 2024.", 10)]

    def fake_run_sync(_prompt: str, *, deps: object) -> object:  # noqa: ARG001
        raise UnexpectedModelBehavior("output validator rejected response twice (invalid citation tags)")

    monkeypatch.setattr(
        generation,
        "_generator_agent",
        lambda _settings: SimpleNamespace(run_sync=fake_run_sync),
    )

    answer, usage = generate_answer_with_agent(
        question="What was Apple's revenue?",
        evidence=evidence,
        plan=None,
        settings=_settings(),
    )

    assert usage.is_empty()
    assert answer.insufficiency_reason is not None
    assert "citations" in answer.insufficiency_reason.lower() or "agent failed" in answer.insufficiency_reason.lower()
    assert answer.metadata["generator"].startswith("local-extractive")
