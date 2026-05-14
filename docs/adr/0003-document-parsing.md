# ADR-0003: Document Parsing

## Status

Accepted

## Context

SEC filing PDFs contain narrative text, financial tables, page headers/footers, and occasional layout artifacts. The system must preserve table fidelity and source-page citations.

Direct Mistral OCR is the primary parser, with Docling available as a fallback. Other AI services use OpenRouter, but OCR remains a direct document-processing integration.

## Decision

Use Mistral OCR as the primary PDF parser.

Request structured page output with table formatting preserved as Markdown or HTML. Store raw OCR responses in MinIO before transformation.

Use Docling only when:

- Mistral OCR fails for a document or page.
- OCR output has empty or clearly malformed page text.
- Table output is unusable for a page that appears table-heavy.
- The evaluation pipeline is running a parser comparison experiment.

Each parsed page must retain:

- Document id.
- Page number.
- Parser name and version/model.
- Raw MinIO source object key and version id.
- Parser artifact key.
- Extracted Markdown/text.
- Extracted table blocks if present.

## Consequences

- The parsing implementation has a dedicated OCR path that is independent of the OpenRouter LLM/embedding/rerank gateway.
- Parser artifacts provide an audit trail for citations and evaluation.
- Docling remains a quality fallback without doubling normal ingestion cost.
- Parser quality checks must be implemented before chunking.

## Parser Quality Checks

At minimum, flag a page for fallback or review when:

- Extracted text is empty or below a minimum character threshold.
- A page has many numeric tokens but no detected table block.
- A Markdown table is syntactically malformed.
- The parser returns inconsistent page numbering.

## Alternatives Considered

- Docling primary: rejected because the architecture standardizes on Mistral OCR as the primary parser.
- Dual parse all critical pages: rejected for v1 because it increases cost and complexity.
- Text-only PDF extraction: rejected because table fidelity is a core system requirement.

## References

- Mistral OCR processor: https://docs.mistral.ai/studio-api/document-processing/basic_ocr
- Docling advanced PDF/table options: https://docling-project.github.io/docling/usage/advanced_options/
