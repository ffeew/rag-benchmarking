# ADR-0007: Background Jobs

## Status

Accepted. **Amended**: evaluations now run as in-process daemon threads inside the API (see commit `5af2dc7`); the stuck-job sweeper is invoked synchronously via `POST /v1/jobs/sweep`, not on a beat schedule; orphan trace retention is handled by FK `ondelete="CASCADE"` from `datasets` to `query_traces` rather than a periodic purge. As a result, the only Celery queue is `ingestion`; the `beat` and `maintenance-worker` services have been removed from `docker-compose.yml`.

## Context

Ingestion can involve MinIO I/O, Mistral OCR calls, Docling fallback, table validation, chunking, OpenRouter embedding batches, database writes, and evaluation runs. These operations can be slow and should not run inside FastAPI request handlers.

The architecture uses an external queue with Celery plus Redis.

## Decision

Use Celery with Redis as the broker and result backend for ingestion and evaluation jobs.

FastAPI creates job records in Postgres and enqueues Celery tasks. Celery workers update durable job state in Postgres. Redis is not the system of record.

Use separate queues for:

- Document registration/upload processing.
- OCR/parsing.
- Chunking/indexing.
- Evaluation.

## Consequences

- Long-running OCR and indexing work can retry independently of API requests.
- The API can expose progress and failure details through job endpoints.
- Docker Compose must run Redis and at least one worker.
- Operational docs must explain how to restart failed jobs and inspect logs.

## Retry Policy

Use bounded retries by failure type:

- Transient provider/network failures: retry with exponential backoff.
- Parser validation failure: attempt Docling fallback once.
- Deterministic validation or schema errors: fail the job and expose actionable details.
- Duplicate document checksum: mark as already ingested or create a new ingestion run without duplicating raw storage.

## Alternatives Considered

- FastAPI background tasks: rejected because they are weak for long OCR jobs and worker restarts.
- Postgres-only job polling: rejected because the architecture standardizes on an external queue.
- RQ or Dramatiq: rejected because Celery is more familiar and feature-complete for retries and queue routing.

## References

- Celery Redis broker/backend: https://docs.celeryq.dev/en/v5.6.3/getting-started/backends-and-brokers/redis.html
- Redis Docker usage: https://redis.io/docs/latest/operate/oss_and_stack/install/install-stack/docker/
