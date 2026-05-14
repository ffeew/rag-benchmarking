from rag_common.schemas import QueryFilters
from rag_retrieval.planning import infer_query_plan


def test_plan_query_extracts_known_ticker_form_and_latest() -> None:
    plan = infer_query_plan(
        question="What is TSLA current long-term debt in its latest 10-K?",
        filters=QueryFilters(),
        known_tickers={"TSLA"},
    )

    assert plan.forms == ["10-K"]
    assert plan.latest is True
    assert plan.target_tickers == ["TSLA"]
    assert "debt" in plan.metrics
