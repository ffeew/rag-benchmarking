from fastapi.testclient import TestClient


def test_v1_missing_route_returns_json_404(client: TestClient) -> None:
    """The SPA fallback must never swallow missing /v1/* routes as HTML responses."""
    response = client.get("/v1/does-not-exist")
    assert response.status_code == 404
    # Content-type is JSON, not the SPA's text/html
    content_type = response.headers.get("content-type", "")
    assert "json" in content_type


def test_health_missing_subpath_returns_404(client: TestClient) -> None:
    response = client.get("/health/extra")
    assert response.status_code == 404
