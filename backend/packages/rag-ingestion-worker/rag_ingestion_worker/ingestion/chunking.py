import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from chonkie import OverlapRefinery, RecursiveChunker, TableChunker
from rag_common.config import Settings, get_settings
from rag_common.db.models import ParsedPage
from rag_common.enums import ChunkerType, ChunkType

logger = logging.getLogger(__name__)


TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$")
TOKEN_ENCODING = "cl100k_base"  # noqa: S105 - tiktoken encoding name, not a credential


@dataclass(frozen=True)
class ChunkDraft:
    text: str
    page_start: int
    page_end: int
    contains_table: bool
    token_count: int
    metadata: dict[str, Any]
    source_offsets: dict[str, Any]


@lru_cache(maxsize=1)
def _tiktoken_encoder() -> Any:
    try:
        import tiktoken

        return tiktoken.get_encoding(TOKEN_ENCODING)
    except Exception as exc:  # noqa: BLE001 - offline boot or missing model: fall back to char heuristic
        logger.warning("tiktoken_encoder_fallback", extra={"error": str(exc)})
        return None


def estimate_tokens(text: str) -> int:
    encoder = _tiktoken_encoder()
    if encoder is None:
        # cl100k averages ~4 chars/token on English prose; the fallback keeps
        # assembly-loop budgeting roughly correct when tiktoken can't load.
        return max(1, len(text) // 4)
    return max(1, len(encoder.encode(text, disallowed_special=())))


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


def protected_blocks(text: str, settings: Settings | None = None) -> list[tuple[str, bool]]:  # noqa: ARG001 - settings retained for API stability
    """Split a page into (text, is_table) blocks so prose and tables can be routed to different chunkers.

    Tables are emitted whole. ``TableChunker`` (token-aware, header-repeating) splits them downstream
    if they exceed the embedder window; below that threshold they stay as one chunk, which is what
    you want for 10-K financial tables where the row-to-row relationship is the signal.
    """
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
        content = "\n".join(table_buffer).strip()
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
        return RecursiveChunker.from_recipe(
            "markdown",
            lang="en",
            tokenizer=TOKEN_ENCODING,
            chunk_size=chunk_size,
        )
    except Exception as exc:  # noqa: BLE001 - recipe fetch or tokenizer load can fail offline
        logger.warning("recursive_chunker_recipe_fallback", extra={"error": str(exc)})
        return RecursiveChunker(tokenizer="character", chunk_size=chunk_size * 4)


@lru_cache(maxsize=4)
def _overlap_refinery(overlap_tokens: int) -> OverlapRefinery | None:
    if overlap_tokens <= 0:
        return None
    try:
        # prefix-mode prepends the trailing context of chunk N onto the start
        # of chunk N+1, so the original text of each chunk is still findable
        # in the source document (suffix-mode would mutate chunk N).
        return OverlapRefinery(
            tokenizer=TOKEN_ENCODING,
            context_size=overlap_tokens,
            mode="token",
            method="prefix",
            inplace=False,
        )
    except Exception as exc:  # noqa: BLE001 - tokenizer load can fail offline; degrade to no-overlap
        logger.warning("overlap_refinery_unavailable", extra={"error": str(exc)})
        return None


def active_tokenizer_mode(chunk_size: int) -> str:
    """Return the tokenizer the chunker actually loaded for ``chunk_size``.

    Used by ``pipeline.chunking_config`` so the persisted run-dedup key reflects the
    real chunking semantics. A character-mode fallback produces incompatible chunk
    boundaries from a cl100k_base run; treating them as the same artifact would
    silently let an offline-boot worker reuse production-quality chunks.
    """
    chunker = _recursive_chunker(chunk_size)
    tokenizer = getattr(chunker, "tokenizer", None)
    name = getattr(tokenizer, "model_name", None) or getattr(tokenizer, "name", None)
    if isinstance(name, str):
        return name
    return "character" if "character" in repr(tokenizer).lower() else TOKEN_ENCODING


@lru_cache(maxsize=4)
def _table_chunker(chunk_size_tokens: int) -> TableChunker:
    try:
        return TableChunker(tokenizer=TOKEN_ENCODING, chunk_size=chunk_size_tokens)
    except Exception as exc:  # noqa: BLE001 - tokenizer load can fail offline
        logger.warning("table_chunker_tokenizer_fallback", extra={"error": str(exc)})
        # Row-mode fallback keeps the pipeline working with rough sizing
        # (assume ~20 tokens per typical financial row).
        return TableChunker(tokenizer="row", chunk_size=max(3, chunk_size_tokens // 20))


def _chunk_narrative(text: str, target_tokens: int, overlap_tokens: int) -> list[str]:
    chunker = _recursive_chunker(target_tokens)
    chunks = chunker.chunk(text)
    if len(chunks) > 1:
        refinery = _overlap_refinery(overlap_tokens)
        if refinery is not None:
            chunks = refinery.refine(chunks)
    return [chunk.text for chunk in chunks if chunk.text.strip()]


def _chunk_table(text: str, max_tokens: int) -> list[str]:
    chunker = _table_chunker(max_tokens)
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

    def chunk_type_for(parts: list[str], *, has_table: bool) -> ChunkType:
        if has_table and len(parts) > 1:
            return ChunkType.MIXED
        if has_table:
            return ChunkType.TABLE
        return ChunkType.NARRATIVE

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
                    "chunker": ChunkerType.CHONKIE,
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
    overlap_tokens = resolved.chunk_overlap_tokens

    for page in sorted(pages, key=lambda item: item.page_number):
        for block, is_table in protected_blocks(page.text, resolved):
            if is_table:
                pieces = _chunk_table(block, max_tokens)
            else:
                pieces = _chunk_narrative(block, target_tokens, overlap_tokens)
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
                                "chunk_type": ChunkType.TABLE,
                                "chunker": ChunkerType.CHONKIE,
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
