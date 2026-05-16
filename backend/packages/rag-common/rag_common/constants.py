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

# Dimensionality of the pgvector ``chunks.embedding_vector`` column. The column
# is declared ``vector(N)`` which enforces N at INSERT/UPDATE time, and the HNSW
# cosine index built on it (``ix_chunks_embedding_vector_hnsw``) is fixed to that
# same N. Any code that reads ``Settings.embedding_dimension`` must agree with
# this constant; ``Settings`` validates the match at load time and refuses to
# start otherwise. Changing this value requires a new migration that alters
# the column type and rebuilds the HNSW index. The column lived in a separate
# ``embeddings`` table prior to migration 0004_consolidate_chunk_embedding.py.
EMBEDDING_VECTOR_DIMENSION: Final = 1024
