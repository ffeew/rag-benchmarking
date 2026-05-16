import pytest
from fastapi.testclient import TestClient
from rag_common.db import models
from rag_common.schemas import (
    CitationRead,
    EvidenceRead,
    QueryRequest,
    QueryResponse,
)
from sqlalchemy.orm import Session


def _build_response() -> QueryResponse:
    return QueryResponse(
        answer="Mocked answer.",
        citations=[
            CitationRead(
                document_id="doc1",
                ticker="AAPL",
                form_type="10-K",
                filing_date=None,
                report_period=None,
                page_number=10,
                chunk_id="c1",
                minio_bucket="b",
                minio_key="k",
                minio_version_id=None,
                snippet="evidence",
                label="[AAPL]",
            )
        ],
        evidence=[
            EvidenceRead(
                chunk_id="c1",
                document_id="doc1",
                ticker="AAPL",
                form_type="10-K",
                filing_date=None,
                page_start=10,
                page_end=11,
                contains_table=False,
                score=0.9,
                snippet="evidence",
            )
        ],
        trace_id="trace-1",
        confidence=0.8,
    )


def test_query_returns_mocked_response(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    seed_dataset: models.Dataset,
) -> None:
    from rag_benchmarking.api.routes import query as query_route

    canned = _build_response()

    def fake_run_query(session: object, *, request: QueryRequest, settings: object) -> QueryResponse:  # noqa: ARG001
        return canned

    monkeypatch.setattr(query_route, "run_query", fake_run_query)

    response = client.post(
        "/v1/query",
        json={"dataset_id": seed_dataset.id, "question": "What was revenue?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Mocked answer."
    assert body["trace_id"] == "trace-1"
    assert len(body["citations"]) == 1


def test_query_unknown_dataset_returns_404(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    from rag_benchmarking.api.routes import query as query_route

    def fake_run_query(session: object, *, request: QueryRequest, settings: object) -> QueryResponse:  # noqa: ARG001
        raise ValueError("Dataset missing was not found")

    monkeypatch.setattr(query_route, "run_query", fake_run_query)
    response = client.post(
        "/v1/query",
        json={"dataset_id": "missing", "question": "What?"},
    )
    assert response.status_code == 404


def test_trace_returns_404_when_missing(client: TestClient) -> None:
    response = client.get("/v1/traces/missing-id")
    assert response.status_code == 404


def test_trace_returns_persisted_trace(
    client: TestClient,
    seed_dataset: models.Dataset,
    db_session: Session,
) -> None:
    trace = models.QueryTrace(
        dataset_id=seed_dataset.id,
        user_question="q",
        retrieval_mode="full_agentic",
        plan={},
        retrieval_calls=[],
        verifier_result={},
        model_metadata={},
        final_answer_metadata={},
        timings={},
    )
    db_session.add(trace)
    db_session.commit()
    response = client.get(f"/v1/traces/{trace.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == trace.id
    assert body["user_question"] == "q"


def _make_trace(
    db_session: Session,
    dataset_id: str,
    *,
    question: str,
    mode: str = "full_agentic",
    confidence: float | None = 0.7,
) -> models.QueryTrace:
    trace = models.QueryTrace(
        dataset_id=dataset_id,
        user_question=question,
        retrieval_mode=mode,
        plan={},
        retrieval_calls=[],
        verifier_result={"confidence": confidence} if confidence is not None else {},
        model_metadata={},
        final_answer_metadata={},
        timings={},
    )
    db_session.add(trace)
    db_session.commit()
    return trace


def test_list_traces_returns_summary_rows(
    client: TestClient,
    seed_dataset: models.Dataset,
    db_session: Session,
) -> None:
    a = _make_trace(db_session, seed_dataset.id, question="alpha question", confidence=0.6)
    b = _make_trace(db_session, seed_dataset.id, question="beta question", confidence=0.9)

    response = client.get("/v1/traces", params={"limit": 50})
    assert response.status_code == 200
    body = response.json()
    ids = {row["id"] for row in body}
    assert {a.id, b.id} <= ids
    summary = next(row for row in body if row["id"] == b.id)
    assert summary["user_question"] == "beta question"
    assert summary["dataset_id"] == seed_dataset.id
    assert summary["confidence"] == 0.9
    assert summary["retrieval_mode"] == "full_agentic"


def test_list_traces_filters_by_question_contains(
    client: TestClient,
    seed_dataset: models.Dataset,
    db_session: Session,
) -> None:
    _make_trace(db_session, seed_dataset.id, question="revenue trend")
    _make_trace(db_session, seed_dataset.id, question="margin overview")

    response = client.get("/v1/traces", params={"question_contains": "revenue"})
    assert response.status_code == 200
    body = response.json()
    questions = {row["user_question"] for row in body}
    assert questions == {"revenue trend"}


def test_list_traces_handles_missing_confidence(
    client: TestClient,
    seed_dataset: models.Dataset,
    db_session: Session,
) -> None:
    trace = _make_trace(db_session, seed_dataset.id, question="q", confidence=None)
    response = client.get("/v1/traces", params={"limit": 50})
    assert response.status_code == 200
    body = response.json()
    summary = next(row for row in body if row["id"] == trace.id)
    assert summary["confidence"] is None
