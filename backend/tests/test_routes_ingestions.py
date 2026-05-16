from fastapi.testclient import TestClient
from rag_common.db import models
from rag_common.enums import IngestionRunStatus
from sqlalchemy.orm import Session


def _seed_run(
    db_session: Session,
    document: models.Document,
    *,
    status: str = IngestionRunStatus.COMPLETED,
    embedding_model: str = "text-embedding-3-small",
    counts: dict | None = None,
    timings: dict | None = None,
    error_summary: str | None = None,
) -> models.IngestionRun:
    run = models.IngestionRun(
        dataset_id=document.dataset_id,
        document_id=document.id,
        parser_config={"parser": "pypdf"},
        chunking_config={"size": 800},
        embedding_model=embedding_model,
        status=status,
        timings=timings or {"parse_ms": 100, "embed_ms": 200},
        counts=counts or {"chunks": 5, "pages": 3},
        error_summary=error_summary,
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def test_list_ingestion_runs_returns_dataset_runs(
    client: TestClient,
    db_session: Session,
    seed_dataset: models.Dataset,
    seed_document: models.Document,
) -> None:
    run = _seed_run(db_session, seed_document)

    response = client.get(f"/v1/datasets/{seed_dataset.id}/ingestion-runs")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 1
    row = body[0]
    assert row["id"] == run.id
    assert row["dataset_id"] == seed_dataset.id
    assert row["document_id"] == seed_document.id
    assert row["status"] == IngestionRunStatus.COMPLETED
    assert row["embedding_model"] == "text-embedding-3-small"
    assert row["counts"] == {"chunks": 5, "pages": 3}
    assert row["timings"] == {"parse_ms": 100, "embed_ms": 200}
    assert row["error_summary"] is None
    assert "created_at" in row


def test_list_ingestion_runs_orders_newest_first(
    client: TestClient,
    db_session: Session,
    seed_dataset: models.Dataset,
    seed_document: models.Document,
) -> None:
    older = _seed_run(db_session, seed_document, status=IngestionRunStatus.COMPLETED)
    newer = _seed_run(db_session, seed_document, status=IngestionRunStatus.FAILED, error_summary="boom")

    response = client.get(f"/v1/datasets/{seed_dataset.id}/ingestion-runs")

    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body] == [newer.id, older.id]
    assert body[0]["error_summary"] == "boom"


def test_list_ingestion_runs_404s_for_unknown_dataset(client: TestClient) -> None:
    response = client.get("/v1/datasets/does-not-exist/ingestion-runs")
    assert response.status_code == 404


def test_list_ingestion_runs_empty_for_dataset_with_no_runs(
    client: TestClient, seed_dataset: models.Dataset
) -> None:
    response = client.get(f"/v1/datasets/{seed_dataset.id}/ingestion-runs")
    assert response.status_code == 200
    assert response.json() == []
