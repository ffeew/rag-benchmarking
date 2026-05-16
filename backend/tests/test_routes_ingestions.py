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


def test_list_ingestion_runs_returns_paginated_dataset_runs(
    client: TestClient,
    db_session: Session,
    seed_dataset: models.Dataset,
    seed_document: models.Document,
) -> None:
    run = _seed_run(db_session, seed_document)

    response = client.get(f"/v1/datasets/{seed_dataset.id}/ingestion-runs")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    row = body["items"][0]
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
    assert [row["id"] for row in body["items"]] == [newer.id, older.id]
    assert body["items"][0]["error_summary"] == "boom"


def test_list_ingestion_runs_respects_limit_and_offset(
    client: TestClient,
    db_session: Session,
    seed_dataset: models.Dataset,
    seed_document: models.Document,
) -> None:
    runs = [_seed_run(db_session, seed_document) for _ in range(5)]
    # Newest-first ordering means runs[-1] is page 1's first item.
    ids_desc = [r.id for r in reversed(runs)]

    page1 = client.get(
        f"/v1/datasets/{seed_dataset.id}/ingestion-runs",
        params={"limit": 2, "offset": 0},
    )
    page2 = client.get(
        f"/v1/datasets/{seed_dataset.id}/ingestion-runs",
        params={"limit": 2, "offset": 2},
    )
    page3 = client.get(
        f"/v1/datasets/{seed_dataset.id}/ingestion-runs",
        params={"limit": 2, "offset": 4},
    )

    for resp in (page1, page2, page3):
        assert resp.status_code == 200
        assert resp.json()["total"] == 5
        assert resp.json()["limit"] == 2

    assert [r["id"] for r in page1.json()["items"]] == ids_desc[0:2]
    assert [r["id"] for r in page2.json()["items"]] == ids_desc[2:4]
    assert [r["id"] for r in page3.json()["items"]] == ids_desc[4:5]
    assert page1.json()["offset"] == 0
    assert page3.json()["offset"] == 4


def test_list_ingestion_runs_404s_for_unknown_dataset(client: TestClient) -> None:
    response = client.get("/v1/datasets/does-not-exist/ingestion-runs")
    assert response.status_code == 404


def test_list_ingestion_runs_empty_for_dataset_with_no_runs(
    client: TestClient, seed_dataset: models.Dataset
) -> None:
    response = client.get(f"/v1/datasets/{seed_dataset.id}/ingestion-runs")
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}
