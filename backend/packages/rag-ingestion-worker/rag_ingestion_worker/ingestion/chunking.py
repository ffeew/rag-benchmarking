from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from chonkie import RecursiveChunker, TableChunker
from rag_common.config import Settings, get_settings

if TYPE_CHECKING:
    from rag_common.db.models import ParsedPage


logger = logging.getLogger(__name__)


TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$")


@dataclass(frozen=True)
class ChunkDraft:
    text: str
    page_start: int
    page_end: int
    contains_table: bool
    token_count: int
    metadata: dict[str, Any]
    source_offsets: dict[str, Any]


def estimate_tokens(text: str) -> int:
    return max(1, int(len(re.findall(r"\S+", text)) * 1.25))


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def markdown_table_count(text: str) -> int:
    lines = text.splitlines()
    count = 0
    in_table = False
    for line in lines:
        is_row = bool(TABLE_ROW_RE.match(line))
        if is_row and not in_table:
            count += 1
        in_table = is_row
    return count


def has_malformed_markdown_table(text: str) -> bool:
    table_lines = [line for line in text.splitlines() if TABLE_ROW_RE.match(line)]
    if len(table_lines) < 2:
        return False
    widths = [line.count("|") for line in table_lines]
    return max(widths) - min(widths) > 2


def split_table_block(lines: list[str], max_rows: int) -> list[list[str]]:
    if len(lines) <= max_rows:
        return [lines]
    header = lines[:2] if len(lines) > 2 and set(lines[1].replace("|", "").strip()) <= {"-", ":"} else lines[:1]
    body = lines[len(header) :]
    blocks: list[list[str]] = []
    for offset in range(0, len(body), max_rows - len(header)):
        blocks.append([*header, *body[offset : offset + max_rows - len(header)]])
    return blocks


def protected_blocks(text: str, settings: Settings) -> list[tuple[str, bool]]:
    blocks: list[tuple[str, bool]] = []
    table_buffer: list[str] = []
    narrative_buffer: list[str] = []

    def flush_narrative() -> None:
        nonlocal narrative_buffer
        content = "\n".join(narrative_buffer).strip()
        if content:
            blocks.append((content, False))
        narrative_buffer = []

    def flush_table() -> None:
        nonlocal table_buffer
        if not table_buffer:
            return
        flush_narrative()
        for table_lines in split_table_block(table_buffer, settings.table_max_rows):
            content = "\n".join(table_lines).strip()
            if content:
                blocks.append((content, True))
        table_buffer = []

    for line in text.splitlines():
        if TABLE_ROW_RE.match(line):
            table_buffer.append(line)
        else:
            flush_table()
            narrative_buffer.append(line)
    flush_table()
    flush_narrative()
    return blocks


@lru_cache(maxsize=4)
def _recursive_chunker(chunk_size: int) -> RecursiveChunker:
    try:
        return RecursiveChunker(tokenizer="cl100k_base", chunk_size=chunk_size)
    except Exception as exc:  # noqa: BLE001 - tokenizer load can fail offline
        logger.warning("recursive_chunker_tokenizer_fallback", extra={"error": str(exc)})
        return RecursiveChunker(tokenizer="character", chunk_size=chunk_size * 4)


@lru_cache(maxsize=4)
def _table_chunker(max_rows: int) -> TableChunker:
    return TableChunker(chunk_size=max_rows)


def _chunk_narrative(text: str, target_tokens: int) -> list[str]:
    chunker = _recursive_chunker(target_tokens)
    return [chunk.text for chunk in chunker.chunk(text) if chunk.text.strip()]


def _chunk_table(text: str, max_rows: int) -> list[str]:
    chunker = _table_chunker(max_rows)
    pieces = [chunk.text for chunk in chunker.chunk(text) if chunk.text.strip()]
    return pieces if pieces else [text]


def chunk_pages(pages: list[ParsedPage], settings: Settings | None = None) -> list[ChunkDraft]:
    resolved = settings or get_settings()
    drafts: list[ChunkDraft] = []
    current_parts: list[str] = []
    current_start: int | None = None
    current_end: int | None = None
    current_has_table = False
    block_index = 0

    def chunk_type_for(parts: list[str], *, has_table: bool) -> str:
        if has_table and len(parts) > 1:
            return "mixed"
        if has_table:
            return "table"
        return "narrative"

    def flush() -> None:
        nonlocal current_parts, current_start, current_end, current_has_table
        text = "\n\n".join(part for part in current_parts if part.strip()).strip()
        if not text or current_start is None or current_end is None:
            current_parts = []
            current_start = None
            current_end = None
            current_has_table = False
            return
        drafts.append(
            ChunkDraft(
                text=text,
                page_start=current_start,
                page_end=current_end,
                contains_table=current_has_table,
                token_count=estimate_tokens(text),
                metadata={
                    "chunk_type": chunk_type_for(current_parts, has_table=current_has_table),
                    "chunker": "chonkie",
                },
                source_offsets={
                    "block_start": block_index - len(current_parts),
                    "block_end": block_index,
                },
            )
        )
        current_parts = []
        current_start = None
        current_end = None
        current_has_table = False

    target_tokens = resolved.chunk_target_tokens
    max_tokens = resolved.chunk_max_tokens

    for page in sorted(pages, key=lambda item: item.page_number):
        for block, is_table in protected_blocks(page.text, resolved):
            if is_table:
                pieces = _chunk_table(block, resolved.table_max_rows)
            else:
                pieces = _chunk_narrative(block, target_tokens)
            for piece in pieces:
                block_index += 1
                piece_tokens = estimate_tokens(piece)
                if is_table and piece_tokens > max_tokens:
                    flush()
                    drafts.append(
                        ChunkDraft(
                            text=piece,
                            page_start=page.page_number,
                            page_end=page.page_number,
                            contains_table=True,
                            token_count=piece_tokens,
                            metadata={
                                "chunk_type": "table",
                                "chunker": "chonkie",
                                "oversized": True,
                            },
                            source_offsets={"block_start": block_index, "block_end": block_index},
                        )
                    )
                    continue

                proposed_tokens = estimate_tokens("\n\n".join([*current_parts, piece]))
                if current_parts and proposed_tokens > target_tokens:
                    flush()

                if current_start is None:
                    current_start = page.page_number
                current_end = page.page_number
                current_parts.append(piece)
                current_has_table = current_has_table or is_table

                if estimate_tokens("\n\n".join(current_parts)) >= target_tokens:
                    flush()

    flush()
    return drafts
