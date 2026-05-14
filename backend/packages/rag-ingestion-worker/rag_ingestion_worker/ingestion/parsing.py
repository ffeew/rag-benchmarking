import io
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import structlog
from pypdf import PdfReader
from rag_common.config import Settings, get_settings
from rag_common.json_types import JsonObject

from rag_ingestion_worker.ingestion.chunking import (
    TABLE_ROW_RE,
    has_malformed_markdown_table,
    markdown_table_count,
)
from rag_ingestion_worker.providers.mistral import MistralOcrClient, OcrProviderError

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ParsedPageDraft:
    page_number: int
    text: str
    parser: str
    table_count: int
    tables: list[JsonObject]
    quality_flags: JsonObject
    raw: JsonObject


@dataclass(frozen=True)
class ParsedDocumentDraft:
    pages: list[ParsedPageDraft]
    raw_ocr: JsonObject
    parser: str
    model: str


def markdown_table_artifacts(text: str) -> list[JsonObject]:
    artifacts: list[JsonObject] = []
    table_buffer: list[str] = []

    def flush_table() -> None:
        nonlocal table_buffer
        if not table_buffer:
            return
        content = "\n".join(table_buffer).strip()
        if content:
            artifacts.append(
                {
                    "index": len(artifacts),
                    "format": "markdown",
                    "source": "inline_markdown",
                    "content": content,
                    "row_count": len(table_buffer),
                }
            )
        table_buffer = []

    for line in text.splitlines():
        if TABLE_ROW_RE.match(line):
            table_buffer.append(line.rstrip())
            continue
        flush_table()
    flush_table()
    return artifacts


def quality_flags_for_text(text: str, table_count: int, page_number: int | None = None) -> JsonObject:
    numeric_tokens = sum(1 for token in text.split() if any(character.isdigit() for character in token))
    flags = {
        "empty_text": not text.strip(),
        "low_text_length": len(text.strip()) < 40,
        "numeric_without_table": numeric_tokens >= 25 and table_count == 0,
        "malformed_markdown_table": has_malformed_markdown_table(text),
        "missing_page_number": page_number is None,
    }
    result: JsonObject = {}
    for key, value in flags.items():
        if value:
            result[key] = value
    return result


@lru_cache(maxsize=1)
def _docling_converter() -> "DocumentConverter":
    """Construct (and cache) the docling DocumentConverter.

    Imports are intentionally lazy: docling pulls torch + transformers on
    first import, which is acceptable on first OCR fallback but should not be
    paid at worker boot or when Mistral OCR is succeeding.
    """
    from docling.document_converter import DocumentConverter

    return DocumentConverter()


def parse_with_docling(pdf_bytes: bytes) -> ParsedDocumentDraft:
    """Layout-aware fallback parser.

    Used after Mistral OCR fails. Calls into docling for structured page
    extraction (markdown text + tables), preserving page boundaries via
    ``DoclingDocument.export_to_markdown(page_no=...)``. Failure is the
    caller's signal to drop to pypdf.
    """
    from docling.datamodel.base_models import DocumentStream

    converter = _docling_converter()
    stream = DocumentStream(name="document.pdf", stream=io.BytesIO(pdf_bytes))
    result = converter.convert(stream)
    doc = result.document

    pages: list[ParsedPageDraft] = []
    # ``doc.pages`` is a ``dict[int, PageItem]`` keyed by 1-indexed page number.
    # Iterating its sorted keys handles sparse cases without depending on
    # ``num_pages()`` (which lacks type annotations in docling-core).
    for page_no in sorted(doc.pages):
        page_md = doc.export_to_markdown(page_no=page_no).strip()
        tables = markdown_table_artifacts(page_md)
        table_count = len(tables) or markdown_table_count(page_md)
        pages.append(
            ParsedPageDraft(
                page_number=page_no,
                text=page_md,
                parser="docling",
                table_count=table_count,
                tables=tables,
                quality_flags=quality_flags_for_text(page_md, table_count, page_no),
                raw={"page_no": page_no},
            )
        )
    return ParsedDocumentDraft(
        pages=pages,
        raw_ocr={"parser": "docling", "page_count": len(pages)},
        parser="docling",
        model="docling-default",
    )


def parse_with_local_pdf(pdf_bytes: bytes) -> ParsedDocumentDraft:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages: list[ParsedPageDraft] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        tables = markdown_table_artifacts(text)
        table_count = len(tables) or markdown_table_count(text)
        pages.append(
            ParsedPageDraft(
                page_number=index,
                text=text.strip(),
                parser="pypdf-local",
                table_count=table_count,
                tables=tables,
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
    """Parse a PDF through the three-tier fallback chain.

    1. Mistral OCR (primary) — layout-aware via the hosted API.
    2. docling (fallback) — local, layout-aware; preserves tables.
    3. pypdf (last resort) — text-only, no layout.

    Each tier is attempted in order; any failure (provider error for Mistral,
    or any exception for docling) falls through to the next tier and is
    logged.
    """
    resolved = settings or get_settings()
    if not resolved.allow_mock_providers:
        try:
            ocr = MistralOcrClient(resolved).parse_pdf(pdf_bytes)
            pages: list[ParsedPageDraft] = []
            for page in ocr.pages:
                tables = page.tables or markdown_table_artifacts(page.markdown)
                table_count = len(tables) or markdown_table_count(page.markdown)
                pages.append(
                    ParsedPageDraft(
                        page_number=page.page_number,
                        text=page.markdown.strip(),
                        parser=ocr.provider,
                        table_count=table_count,
                        tables=tables,
                        quality_flags=quality_flags_for_text(
                            page.markdown,
                            table_count,
                            page.page_number,
                        ),
                        raw=page.raw,
                    )
                )
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
                fallback="docling",
                exception_type=exc.__class__.__name__,
                exception_message=str(exc),
            )

    try:
        return parse_with_docling(pdf_bytes)
    except Exception as exc:  # noqa: BLE001 - any docling failure should fall through to pypdf
        logger.warning(
            "parse_pdf_docling_failed_falling_back",
            parser="docling",
            fallback="pypdf-local",
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
        )

    return parse_with_local_pdf(pdf_bytes)
