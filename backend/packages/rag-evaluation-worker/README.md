# rag-evaluation-worker

Celery worker for SEC filings RAG evaluation runs. Carries the RAGAS metric
stack (faithfulness, answer relevancy, context precision/recall) and the
OpenAI client that RAGAS uses to judge generated answers — so the
`rag-ingestion-worker` image can skip them entirely.

Runs as `celery -A rag_evaluation_worker.celery_app:celery_app worker -Q evaluation`.
