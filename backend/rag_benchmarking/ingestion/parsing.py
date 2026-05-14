import io
from dataclasses import dataclass
from typing import Any

import structlog
from pypdf import PdfReader

from rag_benchmarking.core.config import Settings, get_settings
from rag_benchmarking.ingestion.chunking import (
    has_malformed_markdown_table,
    markdown_table_count,
)
from rag_benchmarking.providers.mistral import MistralOcrClient, OcrProviderError

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ParsedPageDraft:
    page_number: int
    text: str
    parser: str
    table_count: int
    quality_flags: dict[str, Any]
    raw: dict[str, Any]


@dataclass(frozen=True)
class ParsedDocumentDraft:
    pages: list[ParsedPageDraft]
    raw_ocr: dict[str, Any]
    parser: str
    model: str


def quality_flags_for_text(text: str, table_count: int, page_number: int | None = None) -> dict[str, Any]:
    numeric_tokens = sum(1 for token in text.split() if any(character.isdigit() for character in token))
    flags = {
        "empty_text": not text.strip(),
        "low_text_length": len(text.strip()) < 40,
        "numeric_without_table": numeric_tokens >= 25 and table_count == 0,
        "malformed_markdown_table": has_malformed_markdown_table(text),
        "missing_page_number": page_number is None,
    }
    return {key: value for key, value in flags.items() if value}


def parse_with_local_pdf(pdf_bytes: bytes) -> ParsedDocumentDraft:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages: list[ParsedPageDraft] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        table_count = markdown_table_count(text)
        pages.append(
            ParsedPageDraft(
                page_number=index,
                text=text.strip(),
                parser="pypdf-local",
                table_count=table_count,
                quality_flags=quality_flags_for_text(text, table_count, index),
                raw={"page_index": index - 1},
            )
        )
    return ParsedDocumentDraft(
        pages=pages,
        raw_ocr={"parser": "pypdf-local", "page_count": len(pages)},
        parser="pypdf-local",
        model="pypdf",
    )


def parse_pdf(pdf_bytes: bytes, settings: Settings | None = None) -> ParsedDocumentDraft:
    resolved = settings or get_settings()
    if not resolved.allow_mock_providers:
        try:
            ocr = MistralOcrClient(resolved).parse_pdf(pdf_bytes)
            pages = [
                ParsedPageDraft(
                    page_number=page.page_number,
                    text=page.markdown.strip(),
                    parser=ocr.provider,
                    table_count=len(page.tables) or markdown_table_count(page.markdown),
                    quality_flags=quality_flags_for_text(
                        page.markdown,
                        len(page.tables) or markdown_table_count(page.markdown),
                        page.page_number,
                    ),
                    raw=page.raw,
                )
                for page in ocr.pages
            ]
            if pages:
                return ParsedDocumentDraft(
                    pages=pages,
                    raw_ocr=ocr.raw,
                    parser=ocr.provider,
                    model=ocr.model,
                )
        except OcrProviderError as exc:
            logger.warning(
                "parse_pdf_ocr_failed_falling_back",
                parser="mistral-ocr",
                fallback="pypdf-local",
                exception_type=exc.__class__.__name__,
                exception_message=str(exc),
            )
    return parse_with_local_pdf(pdf_bytes)
