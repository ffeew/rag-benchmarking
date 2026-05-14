from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from rag_ingestion_worker.ingestion.chunking import chunk_pages, markdown_table_count

if TYPE_CHECKING:
    from rag_common.config import Settings
    from rag_common.db.models import ParsedPage


def test_markdown_table_count_detects_table_blocks() -> None:
    text = """
Revenue by segment
| Segment | 2025 |
| --- | ---: |
| Cloud | 10 |

More text
"""
    assert markdown_table_count(text) == 1


def test_chunk_pages_preserves_table_block() -> None:
    settings = cast(
        "Settings",
        SimpleNamespace(
            table_max_rows=10,
            chunk_target_tokens=40,
            chunk_max_tokens=200,
        ),
    )
    page = cast(
        "ParsedPage",
        SimpleNamespace(
            page_number=7,
            text="""
Segment revenue
| Segment | 2025 | 2024 |
| --- | ---: | ---: |
| Cloud | 10 | 8 |
| Devices | 5 | 4 |
Narrative after the table.
""",
        ),
    )

    chunks = chunk_pages([page], settings)

    assert chunks
    assert any(chunk.contains_table for chunk in chunks)
    table_chunk = next(chunk for chunk in chunks if chunk.contains_table)
    assert "| Segment | 2025 | 2024 |" in table_chunk.text
    assert "| Cloud | 10 | 8 |" in table_chunk.text
    assert table_chunk.page_start == 7
