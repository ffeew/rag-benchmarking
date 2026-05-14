from datetime import date
from types import SimpleNamespace
from typing import cast

import pytest

from rag_benchmarking.core.config import Settings
from rag_benchmarking.retrieval import generation
from rag_benchmarking.retrieval.generation import GeneratorOutput, generate_answer_with_agent
from rag_benchmarking.retrieval.hybrid import RetrievedChunk


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
            openrouter_chat_model="anthropic/claude-3.5-sonnet",
            allow_mock_providers=False,
        ),
    )


def test_citation_repair_recovers_invalid_first_response(monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = [_retrieved_chunk("c1", "AAPL", "Apple revenue was $394B in 2024.", 10)]
    calls = {"count": 0}

    def fake_run_sync(prompt: str) -> object:  # noqa: ARG001
        calls["count"] += 1
        if calls["count"] == 1:
            output = GeneratorOutput(
                answer="Apple revenue was $394B ##e99.",
                citations_used=["##e99"],
                insufficiency_reason=None,
                confidence=0.8,
            )
        else:
            output = GeneratorOutput(
                answer="Apple revenue was $394B ##e1.",
                citations_used=["##e1"],
                insufficiency_reason=None,
                confidence=0.85,
            )
        return SimpleNamespace(output=output)

    monkeypatch.setattr(
        generation,
        "_generator_agent",
        lambda settings: SimpleNamespace(run_sync=fake_run_sync),  # noqa: ARG005
    )

    answer = generate_answer_with_agent(
        question="What was Apple's revenue?",
        evidence=evidence,
        plan=None,
        settings=_settings(),
    )

    assert calls["count"] == 2
    assert answer.metadata["citation_validation"] == "repaired"
    assert answer.metadata["repair_used"] is True
    assert "[AAPL 2025-01-31 10-K, p. 10]" in answer.answer
    assert "##e1" not in answer.answer


def test_citation_validation_passes_on_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = [_retrieved_chunk("c1", "AAPL", "Apple revenue was $394B in 2024.", 10)]

    def fake_run_sync(prompt: str) -> object:  # noqa: ARG001
        return SimpleNamespace(
            output=GeneratorOutput(
                answer="Apple revenue was $394B ##e1.",
                citations_used=["##e1"],
                insufficiency_reason=None,
                confidence=0.85,
            )
        )

    monkeypatch.setattr(
        generation,
        "_generator_agent",
        lambda settings: SimpleNamespace(run_sync=fake_run_sync),  # noqa: ARG005
    )

    answer = generate_answer_with_agent(
        question="What was Apple's revenue?",
        evidence=evidence,
        plan=None,
        settings=_settings(),
    )

    assert answer.metadata["citation_validation"] == "passed"
    assert answer.metadata["repair_used"] is False
    assert "[AAPL 2025-01-31 10-K, p. 10]" in answer.answer


def test_citation_failure_after_repair_falls_back_to_extractive(monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = [_retrieved_chunk("c1", "AAPL", "Apple revenue was $394B in 2024.", 10)]

    def fake_run_sync(prompt: str) -> object:  # noqa: ARG001
        return SimpleNamespace(
            output=GeneratorOutput(
                answer="Apple revenue was $394B ##e99.",
                citations_used=["##e99"],
                insufficiency_reason=None,
                confidence=0.5,
            )
        )

    monkeypatch.setattr(
        generation,
        "_generator_agent",
        lambda settings: SimpleNamespace(run_sync=fake_run_sync),  # noqa: ARG005
    )

    answer = generate_answer_with_agent(
        question="What was Apple's revenue?",
        evidence=evidence,
        plan=None,
        settings=_settings(),
    )

    assert answer.insufficiency_reason is not None
    assert "citations could not be verified" in answer.insufficiency_reason
    assert answer.metadata["generator"].startswith("local-extractive")
