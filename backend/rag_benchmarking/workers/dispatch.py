"""Dispatch a persisted Job row to its execution path.

This indirection lets API routes, the retry endpoint, and the sweeper all
hand off a Job through the same code path. Callers must persist (commit) the
Job first, then call ``dispatch_job`` and write back the returned task id —
the DB row is the source of truth.

Ingestion jobs still go to a Celery worker (the ingestion image carries
docling/chonkie/mistral OCR deps that don't belong in the API image).
Evaluation jobs now run in-process: ``launch_evaluation_thread`` spawns a
daemon thread inside the current process and returns a sentinel
``inproc:*`` task id so the existing job-tracking machinery (Job row,
sweeper, frontend polling) keeps working unchanged.
"""

import structlog
from rag_common.constants import QUEUE_INGESTION, TASK_INGEST_DOCUMENT
from rag_common.db import models

from rag_benchmarking.evaluation import launch_evaluation_thread
from rag_benchmarking.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


def dispatch_job(job: models.Job) -> str | None:
    """Send `job` to its execution path and return a task id.

    Returns None when an ingestion broker submit was rejected. Evaluation
    dispatch returns the in-process sentinel id and never returns None —
    spawning a thread doesn't have a broker that can fail.
    """
    if job.job_type == "ingestion":
        if not job.document_id:
            raise ValueError(f"Ingestion job {job.id} is missing document_id")
        force = bool((job.metadata_ or {}).get("force", False))
        try:
            result = celery_app.send_task(
                TASK_INGEST_DOCUMENT,
                kwargs={
                    "document_id": job.document_id,
                    "job_id": job.id,
                    "force": force,
                },
                queue=QUEUE_INGESTION,
            )
        except Exception as exc:  # noqa: BLE001 — broker failures must not abort caller
            logger.exception(
                "job_dispatch_failed",
                job_id=job.id,
                job_type=job.job_type,
                exception_type=exc.__class__.__name__,
            )
            return None
        task_id = str(result.id)
        logger.info(
            "job_dispatched",
            job_id=job.id,
            job_type=job.job_type,
            celery_task_id=task_id,
            queue=QUEUE_INGESTION,
        )
        return task_id

    if job.job_type == "evaluation":
        if not job.eval_run_id:
            raise ValueError(f"Evaluation job {job.id} is missing eval_run_id")
        task_id = launch_evaluation_thread(eval_run_id=job.eval_run_id, job_id=job.id)
        logger.info(
            "job_dispatched",
            job_id=job.id,
            job_type=job.job_type,
            celery_task_id=task_id,
            queue="in-process",
        )
        return task_id

    raise ValueError(f"Unknown job_type {job.job_type!r} for job {job.id}")
