from types import SimpleNamespace
from typing import cast

from rag_common.config import Settings
from rag_common.schemas import QueryFilters
from rag_retrieval.planning import plan_query
from rag_retrieval.verification import verify_evidence


def _mock_settings() -> Settings:
    return cast(
        "Settings",
        SimpleNamespace(
            allow_mock_providers=True,
            openrouter_api_key=None,
            openrouter_base_url="https://openrouter.ai/api/v1",
            zai_api_key=None,
            zai_chat_model=None,
            zai_base_url="https://api.z.ai/api/paas/v4",
        ),
    )


def _stub_session(tickers: list[str]) -> object:
    return SimpleNamespace(scalars=lambda _stmt: iter(tickers))


def test_plan_query_falls_back_to_heuristic_in_mock_mode() -> None:
    settings = _mock_settings()
    session = _stub_session(["TSLA"])

    plan, metadata, usage = plan_query(
        session,  # type: ignore[arg-type]
        dataset_id="d1",
        question="What is TSLA's latest 10-K debt?",
        filters=QueryFilters(),
        settings=settings,
    )

    assert plan.target_tickers == ["TSLA"]
    assert plan.forms == ["10-K"]
    assert plan.latest is True
    assert metadata["agent_used"] is False
    assert metadata["fallback_reason"] == "agent_unavailable"
    assert usage.is_empty()


def test_verify_evidence_falls_back_when_no_evidence() -> None:
    settings = _mock_settings()
    result, metadata, usage = verify_evidence("any question", [], settings=settings)

    assert result.supported_chunk_ids == []
    assert result.confidence < 0.3
    assert metadata["agent_used"] is False
    assert metadata["fallback_reason"] == "no_retrieved_evidence"
    assert usage.is_empty()
