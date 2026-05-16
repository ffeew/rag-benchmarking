import json
from typing import cast

import httpx
import pytest
from pydantic import SecretStr
from rag_common.config import Settings
from rag_common.json_types import JsonObject, JsonValue
from rag_ingestion_worker.providers.mistral import (
    MistralOcrClient,
    PermanentOcrProviderError,
)


def _settings() -> Settings:
    return Settings(
        api_bearer_token=SecretStr("test-token"),
        allow_mock_providers=False,
        openrouter_api_key=SecretStr("openrouter-key"),
        openrouter_embedding_model="openai/test-embedding",
        openrouter_rerank_model="cohere/test-rerank",
        zai_api_key=SecretStr("zai-key"),
        zai_chat_model="glm-4.7",
        zai_judge_model="glm-4.7",
        mistral_api_key=SecretStr("mistral-key"),
        mistral_timeout_seconds=2.0,
    )


def _client_for_response(response_payload: JsonObject, requests: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response_payload)

    return httpx.Client(
        base_url="https://api.mistral.ai/v1",
        transport=httpx.MockTransport(handler),
    )


def test_mistral_ocr_sends_document_url_payload_without_table_format() -> None:
    requests: list[httpx.Request] = []
    http_client = _client_for_response(
        {
            "pages": [{"index": 0, "markdown": "Revenue\n"}],
            "model": "mistral-ocr-2512",
            "usage_info": {"pages_processed": 1},
        },
        requests,
    )

    result = MistralOcrClient(_settings(), client=http_client).parse_pdf(b"%PDF")

    assert result.model == "mistral-ocr-2512"
    assert result.raw["usage_info"] == {"pages_processed": 1}
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/v1/ocr"
    assert request.headers["authorization"] == "Bearer mistral-key"
    payload = cast("JsonObject", json.loads(request.content.decode("utf-8")))
    document = cast("JsonObject", payload["document"])
    assert payload["model"] == "mistral-ocr-latest"
    assert payload["include_image_base64"] is False
    assert "table_format" not in payload
    assert document["type"] == "document_url"
    assert document["document_url"] == "data:application/pdf;base64,JVBERg=="


@pytest.mark.parametrize(
    ("response_pages", "expected_page_numbers"),
    [
        ([{"index": 0, "markdown": "page 1"}, {"index": 1, "markdown": "page 2"}], [1, 2]),
        ([{"index": 1, "markdown": "page 1"}, {"index": 2, "markdown": "page 2"}], [1, 2]),
    ],
)
def test_mistral_ocr_normalizes_zero_and_one_based_page_indexes(
    response_pages: list[JsonObject],
    expected_page_numbers: list[int],
) -> None:
    requests: list[httpx.Request] = []
    response_payload: JsonObject = {
        "pages": cast("JsonValue", response_pages),
        "model": "mistral-ocr-2512",
        "usage_info": {"pages_processed": len(response_pages)},
    }
    http_client = _client_for_response(
        response_payload,
        requests,
    )

    result = MistralOcrClient(_settings(), client=http_client).parse_pdf(b"%PDF")

    assert [page.page_number for page in result.pages] == expected_page_numbers


def test_mistral_ocr_falls_back_to_position_when_index_missing() -> None:
    """If a page lacks an ``index`` field, the parser must fall back to the
    1-based stream position so we don't emit ``page_number=0`` or duplicates."""
    requests: list[httpx.Request] = []
    http_client = _client_for_response(
        {
            "pages": [
                {"markdown": "page A"},
                {"markdown": "page B"},
                {"markdown": "page C"},
            ],
            "model": "mistral-ocr-2512",
        },
        requests,
    )

    result = MistralOcrClient(_settings(), client=http_client).parse_pdf(b"%PDF")

    assert [page.page_number for page in result.pages] == [1, 2, 3]


def test_mistral_ocr_mixes_indexed_and_unindexed_pages() -> None:
    """A page with no index uses its stream position; pages with explicit
    indexes are normalized against the detected 0/1-base. The two paths must
    coexist without one corrupting the other."""
    requests: list[httpx.Request] = []
    # Presence of 0 in the indexed pages selects 0-base mode; the middle page
    # has no index and must use stream position 2.
    http_client = _client_for_response(
        {
            "pages": [
                {"index": 0, "markdown": "first"},
                {"markdown": "middle"},
                {"index": 2, "markdown": "third"},
            ],
            "model": "mistral-ocr-2512",
        },
        requests,
    )

    result = MistralOcrClient(_settings(), client=http_client).parse_pdf(b"%PDF")

    assert [page.page_number for page in result.pages] == [1, 2, 3]


def test_mistral_ocr_accepts_string_index_values() -> None:
    """Some Mistral responses return ``"index": "0"`` as a string; ``_as_int``
    coerces it. The page-number logic must then treat it the same as the int."""
    requests: list[httpx.Request] = []
    http_client = _client_for_response(
        {
            "pages": [
                {"index": "0", "markdown": "first"},
                {"index": "1", "markdown": "second"},
            ],
            "model": "mistral-ocr-2512",
        },
        requests,
    )

    result = MistralOcrClient(_settings(), client=http_client).parse_pdf(b"%PDF")

    assert [page.page_number for page in result.pages] == [1, 2]


def test_mistral_ocr_handles_negative_or_zero_normalized_index() -> None:
    """If 1-base mode is selected (no zero appears) and a page still produces a
    normalized value < 1 — e.g., a stray ``"index": -1`` — fall back to the
    stream position rather than emitting ``page_number=0``."""
    requests: list[httpx.Request] = []
    http_client = _client_for_response(
        {
            "pages": [
                {"index": -1, "markdown": "anomalous"},
                {"index": 1, "markdown": "ok"},
                {"index": 2, "markdown": "ok2"},
            ],
            "model": "mistral-ocr-2512",
        },
        requests,
    )

    result = MistralOcrClient(_settings(), client=http_client).parse_pdf(b"%PDF")

    # The presence of 1 (no 0) selects 1-base, so index=-1 normalizes to -1 → < 1
    # → fall back to stream position 1; indexes 1 and 2 pass through.
    assert [page.page_number for page in result.pages] == [1, 1, 2]


def test_mistral_ocr_returns_no_pages_when_response_has_none() -> None:
    """An empty ``pages`` array must produce an empty result without raising."""
    requests: list[httpx.Request] = []
    http_client = _client_for_response(
        {"pages": [], "model": "mistral-ocr-2512"},
        requests,
    )

    result = MistralOcrClient(_settings(), client=http_client).parse_pdf(b"%PDF")

    assert result.pages == []
    assert result.model == "mistral-ocr-2512"


def test_mistral_ocr_retries_transient_statuses() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, text="temporary")
        return httpx.Response(200, json={"pages": [], "model": "mistral-ocr-2512"})

    http_client = httpx.Client(
        base_url="https://api.mistral.ai/v1",
        transport=httpx.MockTransport(handler),
    )

    result = MistralOcrClient(_settings(), client=http_client).parse_pdf(b"%PDF")

    assert calls == 2
    assert result.model == "mistral-ocr-2512"


def test_mistral_ocr_does_not_retry_permanent_statuses() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, text="bad key")

    http_client = httpx.Client(
        base_url="https://api.mistral.ai/v1",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PermanentOcrProviderError):
        MistralOcrClient(_settings(), client=http_client).parse_pdf(b"%PDF")

    assert calls == 1
