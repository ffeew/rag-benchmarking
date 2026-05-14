import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from rag_common.db import models
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

_RETRYABLE_STATUSES = frozenset({"failed", "completed_with_errors", "cancelled"})
_CANCELLABLE_STATUSES = frozenset({"queued", "running"})


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

    Bypasses the maintenance-queue Celery worker on purpose: the operator
    clicked this button precisely because the regular path isn't moving
    things, so we cannot route the recovery through the same broker we
    suspect is partially broken. ``queued_grace_seconds=0`` means fresh
    queued rows are eligible immediately — the scheduled beat sweep keeps
    its conservative 600 s grace for autonomous recovery.
    """
    report = sweeper.run_sweep(
        session,
        now=datetime.now(UTC),
        queued_grace_seconds=0,
        heartbeat_seconds=sweeper.RUNNING_HEARTBEAT_SECONDS,
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
    job.status = "queued"
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
        celery_app.control.revoke(job.celery_task_id, terminate=True, signal="SIGTERM")
    now = datetime.now(UTC)
    job.status = "cancelled"
    job.completed_at = now
    job.last_heartbeat_at = now
    if not job.error:
        job.error = "cancelled by operator"
    session.commit()
    return job_to_read(job)
