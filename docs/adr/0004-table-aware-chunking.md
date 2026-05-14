# ADR-0004: Table-Aware Chunking

## Status

Accepted

## Context

Many target questions require accurate retrieval of financial tables, such as revenue breakdowns, debt values, margins, and multi-year trends. The design keeps tables alongside text while adding Chonkie rules so chunking does not split through the middle of a table.

## Decision

Use Chonkie for chunking with custom preprocessing that marks table blocks as protected regions.

Normal narrative text can be split using semantic or recursive chunking. Table blocks must remain intact unless they exceed the maximum chunk size. Oversized tables are split by row groups while preserving the table header in every resulting chunk.

Chunks can contain:

- Narrative-only content.
- Table-only content.
- Mixed narrative plus adjacent table content when doing so improves context and fits the chunk budget.

Every chunk must keep page-level provenance and character/block offsets where available.

## Consequences

- Numeric/table answers have better retrieval quality than generic text chunking.
- Chunking remains compatible with vector and full-text search because tables stay in Markdown/HTML text form.
- The implementation must include table boundary detection and validation before sending text to Chonkie.
- Very large tables may produce multiple table chunks with repeated headers, increasing chunk count but preserving meaning.

## Chunking Defaults

Use these initial defaults, subject to evaluation tuning:

- Target chunk size: 800 to 1,200 tokens.
- Maximum chunk size: 1,500 tokens.
- Narrative overlap: 100 to 150 tokens.
- Table splitting: row-based with repeated header.
- Chunk metadata: ticker, company, form type, filing date, report period, fiscal year/quarter when available, page range, parser, contains table flag, and source object version.

## Alternatives Considered

- Flatten tables into normal chunks: rejected because it risks splitting rows and headers.
- Store tables separately only: rejected because the system should keep tables near surrounding textual context.
- Build a normalized financial facts layer in v1: rejected because it adds extraction risk and is not required for the initial product scope.

## References

- Chonkie table chunker: https://docs.chonkie.ai/oss/chunkers/table-chunker
- Chonkie semantic chunker: https://docs.chonkie.ai/oss/chunkers/semantic-chunker
