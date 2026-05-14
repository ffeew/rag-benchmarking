"""Dispatch a persisted Job row to its Celery task.

This indirection lets API routes, the retry endpoint, and the sweeper all
hand off a Job through the same code path. Callers must persist (commit) the
Job first, then call ``dispatch_job`` and write back the returned task id —
the DB row is the source of truth.
"""

import structlog

from rag_benchmarking.db import models
from rag_benchmarking.workers.tasks import ingest_document_task, run_evaluation_task

logger = structlog.get_logger(__name__)


def dispatch_job(job: models.Job) -> str | None:
    """Send `job` to its Celery task and return the new task id.

    Returns None when the broker rejected the message. The caller decides
    whether to surface the error to the user; the sweeper will retry the
    row on its next pass regardless of the outcome here.
    """
    if job.job_type == "ingestion":
        if not job.document_id:
            raise ValueError(f"Ingestion job {job.id} is missing document_id")
        force = bool((job.metadata_ or {}).get("force", False))
        try:
            result = ingest_document_task.apply_async(
                kwargs={
                    "document_id": job.document_id,
                    "job_id": job.id,
                    "force": force,
                }
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
            queue="ingestion",
        )
        return task_id

    if job.job_type == "evaluation":
        if not job.eval_run_id:
            raise ValueError(f"Evaluation job {job.id} is missing eval_run_id")
        try:
            result = run_evaluation_task.apply_async(kwargs={"eval_run_id": job.eval_run_id, "job_id": job.id})
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
            queue="evaluation",
        )
        return task_id

    raise ValueError(f"Unknown job_type {job.job_type!r} for job {job.id}")
