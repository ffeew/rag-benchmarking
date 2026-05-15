from fastapi.testclient import TestClient
from rag_common.db import models


def test_create_dataset(client: TestClient) -> None:
    response = client.post(
        "/v1/datasets",
        json={"name": "my-dataset", "description": "test"},
    )
    assert response.status_code in (200, 201)
    body = response.json()
    assert body["name"] == "my-dataset"


def test_list_datasets_empty(client: TestClient) -> None:
    response = client.get("/v1/datasets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_read_dataset_by_id(client: TestClient, seed_dataset: models.Dataset) -> None:
    response = client.get(f"/v1/datasets/{seed_dataset.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == seed_dataset.id


def test_read_unknown_dataset_returns_404(client: TestClient) -> None:
    response = client.get("/v1/datasets/unknown-id")
    assert response.status_code == 404
