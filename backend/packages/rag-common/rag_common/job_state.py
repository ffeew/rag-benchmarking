"""Job state machine writes that bypass the worker's main session.

The worker's primary session holds uncommitted writes for the entire
ingestion run (parsed pages, chunks, embeddings); if we relied on that
session for status updates the row would only become visible to the API/UI
at task completion, and a worker crash would silently roll back every
heartbeat. Both helpers below commit on a fresh transaction so heartbeats
and failure markers survive independently of the main pipeline session.

Row lock is ``FOR KEY SHARE`` rather than ``FOR UPDATE``: the main session
inserts an ``ingestion_runs`` row with an FK to ``jobs``, which acquires
``FOR KEY SHARE`` on the parent. ``FOR UPDATE`` in the helper's separate
session would block on that FK lock — and Postgres cannot break the wait,
because the main session is suspended in user code waiting for the helper
to return. ``FOR KEY SHARE`` is compatible with the FK lock and still
serializes the read-then-write against any actor stronger than us.

Shared by every worker that updates Job rows (``rag-ingestion-worker``,
``rag-evaluation-worker``, plus the sweeper in ``rag_benchmarking.workers``),
so it lives in the rag-common shared kernel.

See also ``rag_common.ingestion_run_state`` for the analogous helper that
protects ``IngestionRun`` rows from the same rollback hazard.
"""

from datetime import UTC, datetime

import structlog

from rag_common.db import models
from rag_common.db.session import get_sessionmaker
from rag_common.enums import JOB_TERMINAL_STATUSES as TERMINAL_STATUSES
from rag_common.enums import JobStatus

__all__ = ["TERMINAL_STATUSES", "commit_job_progress", "record_job_failure"]

logger = structlog.get_logger(__name__)


def commit_job_progress(
    job_id: str | None,
    *,
    status: str,
    progress: int,
    current_step: str | None,
    error: str | None = None,
) -> None:
    """Durably commit a status/progress/heartbeat update on its own transaction.

    Skips the write if the row is already in a terminal state, with one
    exception: a transition into ``"failed"`` is allowed to overwrite earlier
    non-cancel terminals so a final worker exception can still surface its
    error. The ``cancelled`` status is preserved unconditionally.
    """
    if job_id is None:
        return
    log = logger.bind(job_id=job_id, target_status=status, progress=progress, step=current_step)
    log.info("commit_job_progress_called")
    maker = get_sessionmaker()
    try:
        with maker() as session:
            job = session.get(models.Job, job_id, with_for_update={"key_share": True})
            if job is None:
                log.warning("commit_job_progress_job_missing")
                return
            if job.status == JobStatus.CANCELLED:
                log.info("commit_job_progress_skipped_cancelled")
                return
            if job.status in TERMINAL_STATUSES and status != JobStatus.FAILED:
                log.info("commit_job_progress_skipped_terminal", existing_status=job.status)
                return
            now = datetime.now(UTC)
            job.status = status
            job.progress = progress
            job.current_step = current_step
            job.error = error
            job.last_heartbeat_at = now
            if status == JobStatus.RUNNING and job.started_at is None:
                job.started_at = now
            if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.SKIPPED, JobStatus.COMPLETED_WITH_ERRORS}:
                job.completed_at = now
            session.commit()
            log.info("commit_job_progress_committed", last_heartbeat_at=now.isoformat())
    except Exception as exc:
        log.exception(
            "commit_job_progress_failed",
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
        )
        raise


def record_job_failure(job_id: str, error: str) -> None:
    """Persist a failed status on its own transaction after the main session
    was rolled back. Refuses to overwrite a terminal status so operator
    cancellations and runner-set ``completed_with_errors`` are preserved.
    """
    log = logger.bind(job_id=job_id)
    log.info("record_job_failure_called", error=error)
    maker = get_sessionmaker()
    try:
        with maker() as session:
            job = session.get(models.Job, job_id, with_for_update={"key_share": True})
            if job is None:
                log.warning("record_job_failure_job_missing")
                return
            if job.status in TERMINAL_STATUSES:
                log.info("record_job_failure_skipped_terminal", existing_status=job.status)
                return
            now = datetime.now(UTC)
            job.status = JobStatus.FAILED
            job.error = error
            job.completed_at = now
            job.last_heartbeat_at = now
            session.commit()
            log.info("record_job_failure_committed")
    except Exception as exc:
        log.exception(
            "record_job_failure_db_error",
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
        )
        raise
