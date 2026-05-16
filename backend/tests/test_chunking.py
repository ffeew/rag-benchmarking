from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from rag_ingestion_worker.ingestion.chunking import (
    chunk_pages,
    estimate_tokens,
    markdown_table_count,
    protected_blocks,
)

if TYPE_CHECKING:
    from rag_common.config import Settings
    from rag_common.db.models import ParsedPage


def _settings(**overrides: object) -> "Settings":
    defaults: dict[str, object] = {
        "table_max_rows": 10,
        "chunk_target_tokens": 40,
        "chunk_max_tokens": 200,
        "chunk_overlap_tokens": 0,
    }
    defaults.update(overrides)
    return cast("Settings", SimpleNamespace(**defaults))


def _page(page_number: int, text: str) -> "ParsedPage":
    return cast("ParsedPage", SimpleNamespace(page_number=page_number, text=text))


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
    page = _page(
        7,
        """
Segment revenue
| Segment | 2025 | 2024 |
| --- | ---: | ---: |
| Cloud | 10 | 8 |
| Devices | 5 | 4 |
Narrative after the table.
""",
    )

    chunks = chunk_pages([page], _settings())

    assert chunks
    assert any(chunk.contains_table for chunk in chunks)
    table_chunk = next(chunk for chunk in chunks if chunk.contains_table)
    assert "| Segment | 2025 | 2024 |" in table_chunk.text
    assert "| Cloud | 10 | 8 |" in table_chunk.text
    assert table_chunk.page_start == 7


def test_small_table_emits_single_chunk() -> None:
    # A 4-row table well under chunk_max_tokens (=200) must survive as one chunk
    # — splitting financial tables across chunks destroys the row-to-row signal.
    page = _page(
        2,
        """
| Year | Revenue | Profit |
| --- | ---: | ---: |
| 2024 | 100 | 10 |
| 2023 | 90 | 8 |
| 2022 | 80 | 7 |
| 2021 | 70 | 6 |
""",
    )

    chunks = chunk_pages([page], _settings())
    table_chunks = [chunk for chunk in chunks if chunk.contains_table]
    assert len(table_chunks) == 1
    text = table_chunks[0].text
    for row in ("| 2024 | 100 | 10 |", "| 2023 | 90 | 8 |", "| 2021 | 70 | 6 |"):
        assert row in text


def test_large_table_splits_with_header_repeated() -> None:
    # Build a table that exceeds chunk_max_tokens. TableChunker must split it
    # and repeat the header on every piece so each chunk is self-describing.
    header = "| Period | Net Sales | Operating Income | Net Income | EPS |"
    sep = "| --- | ---: | ---: | ---: | ---: |"
    rows = [
        f"| Q{1 + (i % 4)} {2000 + i // 4} | {1000 + i * 11} | {200 + i * 3} | {150 + i * 2} | {1.0 + i * 0.05:.2f} |"
        for i in range(80)
    ]
    table = "\n".join([header, sep, *rows])
    page = _page(11, table)

    chunks = chunk_pages([page], _settings(chunk_max_tokens=150))
    table_chunks = [chunk for chunk in chunks if chunk.contains_table]

    assert len(table_chunks) >= 2, "long table should split into multiple chunks"
    for chunk in table_chunks:
        assert header in chunk.text, "every table chunk must carry the header"


def test_narrative_chunks_apply_overlap_when_configured() -> None:
    # A long prose passage at chunk_target_tokens=40 with overlap=15 should
    # produce overlapping chunks (trailing context of chunk N appears at the
    # start of chunk N+1). Without overlap the chunks would be disjoint.
    sentence = "The Company's revenue grew steadily across all reporting segments. "
    long_prose = "# Management's Discussion\n\n" + (sentence * 40)
    page = _page(3, long_prose)

    chunks = chunk_pages([page], _settings(chunk_target_tokens=40, chunk_overlap_tokens=15))
    narrative = [chunk for chunk in chunks if not chunk.contains_table]
    assert len(narrative) >= 2, "long prose should produce multiple narrative chunks"

    # Token-mode prefix overlap means later chunks should be measurably larger
    # than the target on average (they carry trailing context of the previous).
    later_chunks = narrative[1:]
    overlap_signal = any(estimate_tokens(chunk.text) > 40 for chunk in later_chunks)
    assert overlap_signal, "expected at least one later chunk to exceed the target due to prepended overlap"


def test_protected_blocks_emits_table_as_single_block() -> None:
    # The router must hand a whole table to the table chunker — pre-splitting
    # at the router level was the previous behaviour and double-fragmented tables.
    text = "\n".join(
        ["Prose intro.", "| A | B |", "| --- | --- |"] + [f"| {i} | {i + 1} |" for i in range(50)] + ["Prose after."],
    )

    blocks = protected_blocks(text)
    table_blocks = [block for block, is_table in blocks if is_table]
    assert len(table_blocks) == 1, "router should not split tables; that's TableChunker's job"
    assert table_blocks[0].count("\n") == 51, "header + separator + 50 data rows = 52 lines"


def test_estimate_tokens_uses_real_tokenizer() -> None:
    # cl100k_base counts "Hello, world!" as ~4 tokens; the old word*1.25
    # heuristic counted it as 2 — verify we're using the real tokenizer.
    count = estimate_tokens("Hello, world!")
    assert 3 <= count <= 6, f"expected cl100k_base-style count, got {count}"
