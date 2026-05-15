from typing import Any

import pytest
from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_status(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    # Patch dependency checks to avoid hitting real services
    from rag_common.db import session as session_module
    from rag_common.storage import minio as minio_module
    import redis

    monkeypatch.setattr(session_module, "check_database", lambda *_args, **_kw: True, raising=False)

    def fake_ensure_buckets(self: Any) -> dict[str, Any]:  # noqa: ARG001
        return {"raw": "ok", "artifacts": "ok"}

    monkeypatch.setattr(minio_module.ObjectStore, "ensure_buckets", fake_ensure_buckets, raising=False)

    class FakeRedis:
        @classmethod
        def from_url(cls, *_args: object, **_kwargs: object) -> "FakeRedis":
            return cls()

        def ping(self) -> bool:
            return True

    monkeypatch.setattr(redis, "Redis", FakeRedis)

    response = client.get("/ready")
    assert response.status_code in (200, 503)
    body = response.json()
    assert "status" in body
    assert body["status"] in ("ready", "degraded")
