import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from rag_common.config import get_settings
from rag_common.db import models
from rag_common.enums import JobStatus
from rag_common.schemas import JobRead, JobSweepResponse, Page
from sqlalchemy import select

from rag_benchmarking.api.deps import AuthDep, DbSession
from rag_benchmarking.api.pagination import LimitParam, OffsetParam, paged_query
from rag_benchmarking.api.serialization import job_to_read
from rag_benchmarking.workers import sweeper
from rag_benchmarking.workers.celery_app import celery_app
from rag_benchmarking.workers.dispatch import dispatch_job

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])

_RETRYABLE_STATUSES = frozenset({JobStatus.FAILED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.CANCELLED})
_CANCELLABLE_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})


@router.get("/v1/jobs")
def list_jobs(
    session: DbSession,
    _auth: AuthDep,
    dataset_id: str | None = None,
    job_type: str | None = None,
    # `status` shadows the imported HTTP-constants module — use an alias.
    status_: Annotated[str | None, Query(alias="status")] = None,
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
) -> Page[JobRead]:
    base = select(models.Job)
    if dataset_id:
        base = base.where(models.Job.dataset_id == dataset_id)
    if job_type:
        base = base.where(models.Job.job_type == job_type)
    if status_:
        base = base.where(models.Job.status == status_)
    ordered = base.order_by(models.Job.created_at.desc())
    rows, total = paged_query(session, base=base, ordered=ordered, limit=limit, offset=offset)
    return Page[JobRead](
        items=[job_to_read(job) for job in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/v1/jobs/sweep")
def trigger_sweep(session: DbSession, _auth: AuthDep) -> JobSweepResponse:
    """Run the sweeper inline so the operator gets immediate recovery.

    ``queued_grace_seconds=0`` means fresh queued rows are eligible
    immediately — the operator clicked this button precisely because
    something is stuck, so the conservative defaults aren't useful here.
    """
    settings = get_settings()
    report = sweeper.run_sweep(
        session,
        now=datetime.now(UTC),
        queued_grace_seconds=0,
        heartbeat_seconds=settings.running_heartbeat_seconds,
    )
    session.commit()
    return JobSweepResponse(**report)


@router.get("/v1/jobs/{job_id}")
def read_job(job_id: str, session: DbSession, _auth: AuthDep) -> JobRead:
    job = session.get(models.Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job_to_read(job)


@router.post("/v1/jobs/{job_id}/retry")
def retry_job(job_id: str, session: DbSession, _auth: AuthDep) -> JobRead:
    job = session.get(models.Job, job_id, with_for_update=True)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status not in _RETRYABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot retry a job in status {job.status!r}",
        )
    job.status = JobStatus.QUEUED
    job.error = None
    job.started_at = None
    job.completed_at = None
    job.current_step = "queued (retry)"
    job.progress = 0
    job.last_heartbeat_at = None
    job.celery_task_id = None
    # Operator-initiated retries reset the budget — the MAX_RETRIES cap is for
    # *automatic* sweeper recovery. An explicit click means the user has
    # decided to try again, and we shouldn't refuse based on prior auto-retries.
    job.retry_count = 0
    session.commit()

    task_id = dispatch_job(job)
    if task_id is not None:
        job.celery_task_id = task_id
        session.commit()
    return job_to_read(job)


@router.post("/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str, session: DbSession, _auth: AuthDep) -> JobRead:
    job = session.get(models.Job, job_id, with_for_update=True)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status not in _CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel a job in status {job.status!r}",
        )
    if job.celery_task_id:
        try:
            celery_app.control.revoke(job.celery_task_id, terminate=True, signal="SIGTERM")
        except Exception as exc:  # noqa: BLE001 - kombu/amqp can raise anything; the sweeper reaps unrevoked tasks
            # Mirror the sweeper's pattern (see workers/sweeper.py:78-89): proceed with
            # the DB write so the row reflects operator intent. The worker either honors
            # the revoke on next heartbeat or the sweeper marks it dead.
            logger.warning("cancel_revoke_failed job_id=%s error=%s", job.id, exc, exc_info=True)
    now = datetime.now(UTC)
    job.status = JobStatus.CANCELLED
    job.completed_at = now
    job.last_heartbeat_at = now
    if not job.error:
        job.error = "cancelled by operator"
    # In-process eval threads can't be revoked (see workers/sweeper.py:86-91),
    # so the matching EvalRun row would otherwise stay at ``running`` and the
    # UI would keep polling forever. The runner's terminal-status guards keep
    # the row at CANCELLED even after the thread finishes its loop.
    sweeper.cancel_linked_eval_run(session, job, now=now, reason=job.error)
    session.commit()
    return job_to_read(job)
