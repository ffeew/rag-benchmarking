import pytest
from pydantic import SecretStr
from rag_common.config import Settings
from rag_ingestion_worker.ingestion import parsing
from rag_ingestion_worker.ingestion.parsing import ParsedDocumentDraft, ParsedPageDraft, markdown_table_artifacts
from rag_ingestion_worker.providers.mistral import MistralOcrClient, OcrPage, OcrResult


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
    )


def test_markdown_table_artifacts_extracts_inline_tables() -> None:
    text = """
Revenue by segment
| Segment | 2025 |
| --- | ---: |
| Cloud | 10 |

Narrative after the table.
"""

    tables = markdown_table_artifacts(text)

    assert tables == [
        {
            "index": 0,
            "format": "markdown",
            "source": "inline_markdown",
            "content": "| Segment | 2025 |\n| --- | ---: |\n| Cloud | 10 |",
            "row_count": 3,
        }
    ]


def test_parse_pdf_derives_tables_from_mistral_inline_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    markdown = """
Revenue by segment
| Segment | 2025 |
| --- | ---: |
| Cloud | 10 |
"""

    def fake_parse_pdf(_client: object, pdf_bytes: bytes) -> OcrResult:
        assert pdf_bytes == b"%PDF"
        return OcrResult(
            pages=[
                OcrPage(
                    page_number=1,
                    markdown=markdown,
                    tables=[],
                    raw={"index": 0, "markdown": markdown},
                )
            ],
            raw={"pages": [], "model": "mistral-ocr-2512", "usage_info": {"pages_processed": 1}},
            provider="mistral",
            model="mistral-ocr-2512",
        )

    monkeypatch.setattr(MistralOcrClient, "parse_pdf", fake_parse_pdf)

    parsed = parsing.parse_pdf(b"%PDF", _settings())

    assert parsed.parser == "mistral"
    assert parsed.model == "mistral-ocr-2512"
    assert parsed.pages[0].table_count == 1
    assert parsed.pages[0].tables[0]["content"] == "| Segment | 2025 |\n| --- | ---: |\n| Cloud | 10 |"


def test_parse_pdf_falls_back_when_mistral_returns_no_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_parse_pdf(_client: object, pdf_bytes: bytes) -> OcrResult:
        assert pdf_bytes == b"%PDF"
        return OcrResult(
            pages=[],
            raw={"pages": [], "model": "mistral-ocr-2512", "usage_info": {"pages_processed": 0}},
            provider="mistral",
            model="mistral-ocr-2512",
        )

    def fake_local_pdf(pdf_bytes: bytes) -> ParsedDocumentDraft:
        assert pdf_bytes == b"%PDF"
        return ParsedDocumentDraft(
            pages=[
                ParsedPageDraft(
                    page_number=1,
                    text="fallback text",
                    parser="pypdf-local",
                    table_count=0,
                    tables=[],
                    quality_flags={},
                    raw={"page_index": 0},
                )
            ],
            raw_ocr={"parser": "pypdf-local", "page_count": 1},
            parser="pypdf-local",
            model="pypdf",
        )

    monkeypatch.setattr(MistralOcrClient, "parse_pdf", fake_parse_pdf)
    monkeypatch.setattr(parsing, "parse_with_local_pdf", fake_local_pdf)

    parsed = parsing.parse_pdf(b"%PDF", _settings())

    assert parsed.parser == "pypdf-local"
    assert parsed.pages[0].text == "fallback text"
