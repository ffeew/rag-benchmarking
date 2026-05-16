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


def test_patch_dataset_writes_only_supplied_fields(
    client: TestClient, seed_dataset: models.Dataset
) -> None:
    """PATCH must honor ``exclude_unset`` semantics: unsent fields stay untouched."""
    response = client.patch(
        f"/v1/datasets/{seed_dataset.id}",
        json={
            "domain_label": "Internal compliance memos",
            "valid_forms": ["MEMO", "INCIDENT"],
            "metric_terms": ["incident", "escalation"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["domain_label"] == "Internal compliance memos"
    assert body["valid_forms"] == ["MEMO", "INCIDENT"]
    assert body["metric_terms"] == ["incident", "escalation"]
    # Un-supplied fields stay at their original values - the seed has description set
    # but no overrides; description must not be wiped by an unrelated PATCH call.
    assert body["description"] == seed_dataset.description
    assert body["hyde_style_hint"] is None
    assert body["citation_label_template"] is None


def test_patch_dataset_can_clear_override_with_explicit_null(
    client: TestClient, seed_dataset: models.Dataset
) -> None:
    """Passing ``null`` re-enables the SEC fallback for that override."""
    client.patch(
        f"/v1/datasets/{seed_dataset.id}",
        json={"hyde_style_hint": "Compliance memo register."},
    )
    response = client.patch(
        f"/v1/datasets/{seed_dataset.id}",
        json={"hyde_style_hint": None},
    )
    assert response.status_code == 200
    assert response.json()["hyde_style_hint"] is None


def test_patch_dataset_rejects_name_collision(
    client: TestClient, seed_dataset: models.Dataset
) -> None:
    """Renaming a dataset to an existing name must 409 instead of silently dropping."""
    other = client.post(
        "/v1/datasets",
        json={"name": "other-dataset", "description": "alt"},
    )
    assert other.status_code in (200, 201)

    response = client.patch(
        f"/v1/datasets/{seed_dataset.id}",
        json={"name": "other-dataset"},
    )
    assert response.status_code == 409


def test_patch_unknown_dataset_returns_404(client: TestClient) -> None:
    response = client.patch(
        "/v1/datasets/unknown-id",
        json={"domain_label": "anything"},
    )
    assert response.status_code == 404


def test_patch_dataset_forbids_unknown_field(
    client: TestClient, seed_dataset: models.Dataset
) -> None:
    """``DatasetUpdate`` is ``extra='forbid'`` to surface client typos as 422 errors."""
    response = client.patch(
        f"/v1/datasets/{seed_dataset.id}",
        json={"stopwords": ["the"]},
    )
    assert response.status_code == 422
