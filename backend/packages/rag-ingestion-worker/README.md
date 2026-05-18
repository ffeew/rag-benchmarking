# rag-ingestion-worker

Celery worker for SEC filings ingestion. Owns the PDF + chunking dependencies
(`pypdf`, `chonkie`, the Mistral OCR client) — these stay out of the API and
scheduler images.

Runs as `celery -A rag_ingestion_worker.celery_app:celery_app worker -Q ingestion`.

Evaluation runs (RAGAS scoring, retrieval ablations) live in `rag-evaluation`
— a sibling library that the API imports directly and runs in-process via a
daemon thread.
