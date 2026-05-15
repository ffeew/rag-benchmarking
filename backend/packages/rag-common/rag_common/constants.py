"""Centralized Celery task and queue names.

Producers and consumers must agree on these strings — keep them here so the
producer-only Celery instances in ``rag-api`` / ``rag-scheduler`` and the
``@celery_app.task`` decorators in ``rag-worker`` / ``rag-scheduler`` all
reference the same constant rather than coupling through a Python import.
"""

from typing import Final

TASK_INGEST_DOCUMENT: Final = "rag_benchmarking.ingest_document"
TASK_RUN_EVALUATION: Final = "rag_benchmarking.run_evaluation"
TASK_SWEEP_STUCK_JOBS: Final = "rag_benchmarking.sweep_stuck_jobs"
TASK_PURGE_OLD_TRACES: Final = "rag_benchmarking.purge_old_traces"

QUEUE_INGESTION: Final = "ingestion"
QUEUE_EVALUATION: Final = "evaluation"
QUEUE_MAINTENANCE: Final = "maintenance"
