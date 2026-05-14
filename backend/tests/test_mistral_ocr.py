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
        openrouter_chat_model="openai/test-chat",
        openrouter_judge_model="openai/test-judge",
        openrouter_embedding_model="openai/test-embedding",
        openrouter_rerank_model="cohere/test-rerank",
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
