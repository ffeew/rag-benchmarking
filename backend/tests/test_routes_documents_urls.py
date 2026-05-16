"""Tests for /v1/documents/{id}/file-url and /extracted-url presigned-URL routes.

The MinIO client is patched so the test never reaches a real bucket; the routes
only depend on (a) the document/run rows we seed via fixtures and (b) the
ObjectStore method calls. We assert behaviour through a FakeStore double that
records every call.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from rag_common.db import models
from sqlalchemy.orm import Session


class FakeStore:
    """ObjectStore double that records calls and returns a stable URL."""

    def __init__(self, settings: object) -> None:  # noqa: ARG002 - matches real signature
        self.exists_calls: list[tuple[str, str]] = []
        self.put_text_calls: list[tuple[str, str, str]] = []
        self.presign_calls: list[tuple[str, str, str | None, int]] = []
        self.exists_return = False

    def exists(self, *, bucket: str, key: str) -> bool:
        self.exists_calls.append((bucket, key))
        return self.exists_return

    def put_text(self, *, key: str, text: str, content_type: str = "text/markdown") -> object:
        self.put_text_calls.append((key, text, content_type))
        return None

    def get_presigned_url(
        self,
        *,
        bucket: str,
        key: str,
        version_id: str | None = None,
        expires_seconds: int = 900,
    ) -> str:
        self.presign_calls.append((bucket, key, version_id, expires_seconds))
        return f"https://minio.example/{bucket}/{key}?signed=1"


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeStore]:
    """Patch ObjectStore inside the documents route module with a singleton FakeStore."""
    holder: dict[str, FakeStore] = {}

    def factory(settings: object) -> FakeStore:
        if "store" not in holder:
            holder["store"] = FakeStore(settings)
        return holder["store"]

    import rag_benchmarking.api.routes.documents as documents_module

    monkeypatch.setattr(documents_module, "ObjectStore", factory)
    yield holder.setdefault("store", FakeStore(object()))


@pytest.fixture
def seed_ingested_document(db_session: Session, seed_document: models.Document) -> models.Document:
    """seed_document plus a completed IngestionRun with two parsed pages."""
    run = models.IngestionRun(
        dataset_id=seed_document.dataset_id,
        document_id=seed_document.id,
        parser_config={},
        chunking_config={},
        embedding_model="mock-embedding",
        status="completed",
    )
    db_session.add(run)
    db_session.flush()
    for page_number, text in [(1, "Hello world"), (2, "Second page")]:
        db_session.add(
            models.ParsedPage(
                ingestion_run_id=run.id,
                document_id=seed_document.id,
                page_number=page_number,
                parser="mock",
                artifact_key=f"artifacts/x/y/{run.id}/pages/{page_number}.md",
                text=text,
                text_char_count=len(text),
                source_minio_key=seed_document.minio_key,
            )
        )
    seed_document.active_ingestion_run_id = run.id
    db_session.commit()
    db_session.refresh(seed_document)
    return seed_document


def test_file_url_returns_presigned_url(
    client: TestClient,
    seed_document: models.Document,
    fake_store: FakeStore,
) -> None:
    response = client.get(f"/v1/documents/{seed_document.id}/file-url")

    assert response.status_code == 200
    body = response.json()
    assert body["url"].startswith("https://minio.example/")
    assert "expires_at" in body
    assert fake_store.presign_calls == [
        (seed_document.minio_bucket, seed_document.minio_key, None, 15 * 60),
    ]


def test_file_url_404_for_unknown_document(client: TestClient, fake_store: FakeStore) -> None:
    response = client.get("/v1/documents/does-not-exist/file-url")
    assert response.status_code == 404
    assert fake_store.presign_calls == []


def test_extracted_url_404_when_no_ingestion_run(
    client: TestClient,
    seed_document: models.Document,
    fake_store: FakeStore,
) -> None:
    response = client.get(f"/v1/documents/{seed_document.id}/extracted-url")
    assert response.status_code == 404
    assert fake_store.put_text_calls == []
    assert fake_store.presign_calls == []


def test_extracted_url_lazy_uploads_combined_markdown(
    client: TestClient,
    seed_ingested_document: models.Document,
    fake_store: FakeStore,
) -> None:
    fake_store.exists_return = False

    response = client.get(f"/v1/documents/{seed_ingested_document.id}/extracted-url")

    assert response.status_code == 200
    run_id = seed_ingested_document.active_ingestion_run_id
    expected_key = f"artifacts/{seed_ingested_document.dataset_id}/{seed_ingested_document.id}/{run_id}/extracted.md"
    assert len(fake_store.put_text_calls) == 1
    key, text, content_type = fake_store.put_text_calls[0]
    assert key == expected_key
    assert content_type == "text/plain; charset=utf-8"
    # Combined body uses "## Page N" separators and contains both page texts.
    assert "## Page 1" in text
    assert "Hello world" in text
    assert "## Page 2" in text
    assert "Second page" in text
    # Page 1 must precede page 2 (ordered by page_number).
    assert text.index("Hello world") < text.index("Second page")
    # The combined extracted.md lives in artifact_bucket, not the document's
    # raw bucket. Defaults to "sec-filings" from Settings.
    assert fake_store.presign_calls == [("sec-filings", expected_key, None, 15 * 60)]


def test_extracted_url_skips_upload_when_combined_markdown_exists(
    client: TestClient,
    seed_ingested_document: models.Document,
    fake_store: FakeStore,
) -> None:
    fake_store.exists_return = True

    response = client.get(f"/v1/documents/{seed_ingested_document.id}/extracted-url")

    assert response.status_code == 200
    assert fake_store.put_text_calls == []
    assert len(fake_store.presign_calls) == 1


def test_presigned_url_uses_public_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """ObjectStore.get_presigned_url must mint URLs whose host is the public endpoint."""
    from rag_common.config import Settings
    from rag_common.storage.minio import ObjectStore

    settings = Settings(
        api_bearer_token="t",  # noqa: S106 - test fixture token
        allow_mock_providers=True,
        minio_endpoint="minio:9000",
        minio_public_endpoint="public-minio.example:9000",
    )
    store = ObjectStore(settings)

    url = store.get_presigned_url(bucket="sec-filings", key="raw/x.pdf")

    assert "public-minio.example:9000" in url
    assert "minio:9000" not in url
