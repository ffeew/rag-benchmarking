# ADR-0002: MinIO Object Storage

## Status

Accepted

## Context

The source corpus is a local folder of SEC filing PDFs. The system must support reproducible ingestion, custom datasets, parser debugging, and future reruns with different parsing or chunking settings.

Keeping original PDFs only on local disk makes ingestion less portable and makes it harder to reproduce exactly which document version produced a given chunk or answer.

## Decision

Use MinIO as the canonical document storage layer during ingestion.

The local `sec_filings_pdf/` folder is a seed source only. The ingestion flow first registers/uploads documents to MinIO, then all parsing and indexing jobs read from MinIO object keys.

Store both:

- Raw PDFs.
- Derived parser artifacts, including OCR JSON, page Markdown/text, table-aware intermediate output, and job logs where useful.

Enable bucket versioning for raw PDFs. Use deterministic object keys based on dataset id, ticker, form type, filing date, checksum, and ingestion run id.

## Consequences

- Every chunk and citation can reference the exact object key and version id used to produce it.
- Re-ingestion can be idempotent by document checksum.
- Parser outputs can be inspected without rerunning paid or slow OCR calls.
- Docker Compose must include a MinIO service and startup bucket initialization.

## Object Layout

Use separate prefixes within the same MinIO deployment:

- `raw/{dataset_id}/{ticker}/{form_type}/{filing_date}/{checksum}.pdf`
- `artifacts/{dataset_id}/{document_id}/{run_id}/ocr.json`
- `artifacts/{dataset_id}/{document_id}/{run_id}/pages/{page_number}.md`
- `artifacts/{dataset_id}/{document_id}/{run_id}/tables/{page_number}.json`

## Alternatives Considered

- Raw PDFs only: rejected because parser artifacts are essential for reproducibility and debugging.
- Transient staging only: rejected because it loses auditability.
- Local files as primary source: rejected because custom dataset ingestion should not depend on local paths after registration.

## References

- MinIO container deployment: https://min.io/docs/minio/container/index.html
- MinIO object versioning: https://min.io/docs/minio/kubernetes/upstream/administration/object-management/object-versioning.html
