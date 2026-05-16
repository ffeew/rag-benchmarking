import base64
from dataclasses import dataclass
from typing import Literal, TypedDict, cast

import httpx
from rag_common.config import Settings, get_settings
from rag_common.json_types import JsonObject, JsonValue
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class OcrProviderError(RuntimeError):
    pass


class TransientOcrProviderError(OcrProviderError):
    pass


class PermanentOcrProviderError(OcrProviderError):
    pass


class MistralDocumentUrlRequest(TypedDict):
    type: Literal["document_url"]
    document_url: str


class MistralOcrRequest(TypedDict):
    model: str
    document: MistralDocumentUrlRequest
    include_image_base64: bool


@dataclass(frozen=True)
class OcrPage:
    page_number: int
    markdown: str
    tables: list[JsonObject]
    raw: JsonObject


@dataclass(frozen=True)
class OcrResult:
    pages: list[OcrPage]
    raw: JsonObject
    provider: str
    model: str


def _as_json_object(value: object) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    result: JsonObject = {}
    for key, item in value.items():
        if isinstance(key, str):
            result[key] = cast("JsonValue", item)
    return result


def _as_json_objects(value: JsonValue | None) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    objects: list[JsonObject] = []
    for item in value:
        resolved = _as_json_object(item)
        if resolved is not None:
            objects.append(resolved)
    return objects


def _as_int(value: JsonValue | None) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _as_str(value: JsonValue | None) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _response_page_index_base(indexes: list[int | None]) -> Literal[0, 1]:
    explicit_indexes = [index for index in indexes if index is not None]
    if not explicit_indexes:
        return 0
    if 0 in explicit_indexes:
        return 0
    return 1


def _page_number(raw_index: int | None, position: int, index_base: Literal[0, 1]) -> int:
    if raw_index is None:
        return position
    normalized = raw_index + 1 if index_base == 0 else raw_index
    if normalized < 1:
        return position
    return normalized


def _parse_pages(data: JsonObject) -> list[OcrPage]:
    page_objects = _as_json_objects(data.get("pages"))
    page_indexes = [_as_int(page.get("index")) for page in page_objects]
    index_base = _response_page_index_base(page_indexes)
    pages: list[OcrPage] = []
    for position, page in enumerate(page_objects, start=1):
        markdown = _as_str(page.get("markdown")) or _as_str(page.get("text")) or ""
        raw_index = _as_int(page.get("index"))
        pages.append(
            OcrPage(
                page_number=_page_number(raw_index, position, index_base),
                markdown=markdown,
                tables=_as_json_objects(page.get("tables")),
                raw=page,
            )
        )
    return pages


class MistralOcrClient:
    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(
            base_url=self.settings.mistral_base_url,
            timeout=self.settings.mistral_timeout_seconds,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.settings.mistral_api_key and not self.settings.allow_mock_providers)

    @retry(
        retry=retry_if_exception_type(TransientOcrProviderError),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def parse_pdf(self, pdf_bytes: bytes) -> OcrResult:
        if not self.enabled:
            raise OcrProviderError("Mistral OCR is disabled in mock provider mode")
        api_key = self.settings.mistral_api_key
        if api_key is None:
            raise OcrProviderError("MISTRAL_API_KEY is not configured")
        encoded = base64.b64encode(pdf_bytes).decode("ascii")
        payload: MistralOcrRequest = {
            "model": self.settings.mistral_ocr_model,
            "document": {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{encoded}",
            },
            "include_image_base64": False,
        }
        try:
            response = self._client.post(
                "/ocr",
                headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
                json=payload,
            )
        except httpx.RequestError as exc:
            raise TransientOcrProviderError(f"Mistral OCR request failed: {exc.__class__.__name__}") from exc
        self._raise_for_status(response)
        data = _as_json_object(response.json())
        if data is None:
            raise OcrProviderError("Mistral OCR returned a non-object response")
        model = _as_str(data.get("model")) or self.settings.mistral_ocr_model
        return OcrResult(
            pages=_parse_pages(data),
            raw=data,
            provider="mistral-ocr",
            model=model,
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        message = f"Mistral OCR failed: {response.status_code} {response.text[:500]}"
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientOcrProviderError(message)
        raise PermanentOcrProviderError(message)
