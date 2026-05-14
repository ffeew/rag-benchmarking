import base64
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from rag_benchmarking.core.config import Settings, get_settings


class OcrProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrPage:
    page_number: int
    markdown: str
    tables: list[dict[str, Any]]
    raw: dict[str, Any]


@dataclass(frozen=True)
class OcrResult:
    pages: list[OcrPage]
    raw: dict[str, Any]
    provider: str
    model: str


class MistralOcrClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = httpx.Client(
            base_url=self.settings.mistral_base_url,
            timeout=self.settings.openrouter_timeout_seconds,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.settings.mistral_api_key and not self.settings.allow_mock_providers)

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
    def parse_pdf(self, pdf_bytes: bytes) -> OcrResult:
        if not self.enabled:
            raise OcrProviderError("Mistral OCR is disabled in mock provider mode")
        api_key = self.settings.mistral_api_key
        if api_key is None:
            raise OcrProviderError("MISTRAL_API_KEY is not configured")
        encoded = base64.b64encode(pdf_bytes).decode("ascii")
        payload = {
            "model": self.settings.mistral_ocr_model,
            "document": {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{encoded}",
            },
            "include_image_base64": False,
        }
        response = self._client.post(
            "/ocr",
            headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
            json=payload,
        )
        if response.status_code >= 400:
            raise OcrProviderError(f"Mistral OCR failed: {response.status_code} {response.text[:500]}")
        data = response.json()
        pages: list[OcrPage] = []
        for index, page in enumerate(data.get("pages", []), start=1):
            markdown = page.get("markdown") or page.get("text") or ""
            tables = page.get("tables") or []
            page_number = int(page.get("index", index - 1)) + 1
            pages.append(OcrPage(page_number=page_number, markdown=markdown, tables=tables, raw=page))
        return OcrResult(
            pages=pages,
            raw=data,
            provider="mistral",
            model=self.settings.mistral_ocr_model,
        )
