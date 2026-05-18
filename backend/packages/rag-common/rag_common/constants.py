"""Centralized Celery task and queue names.

Producer (the API) and consumer (the ingestion worker) must agree on these
strings — keep them here so neither side has to import the other's package.
"""

from typing import Final

TASK_INGEST_DOCUMENT: Final = "rag_benchmarking.ingest_document"

QUEUE_INGESTION: Final = "ingestion"

# Dimensionality of the pgvector ``chunks.embedding_vector`` column. The column
# is declared ``vector(N)`` which enforces N at INSERT/UPDATE time, and the HNSW
# cosine index built on it (``ix_chunks_embedding_vector_hnsw``) is fixed to that
# same N. Any code that reads ``Settings.embedding_dimension`` must agree with
# this constant; ``Settings`` validates the match at load time and refuses to
# start otherwise. Changing this value requires a new migration that alters
# the column type and rebuilds the HNSW index.
EMBEDDING_VECTOR_DIMENSION: Final = 1024
