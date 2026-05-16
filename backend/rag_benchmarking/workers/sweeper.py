"""Periodic stuck-job sweeper.

Re-dispatches queued rows whose Celery message demonstrably vanished and
fails running rows that stopped emitting heartbeats. The DB is the source
of truth for what needs to run — this task closes the loop between
persisted intent and broker reality.

The core work lives in :func:`run_sweep`, which takes a session and explicit
grace/heartbeat windows so the ``POST /v1/jobs/sweep`` route can invoke a
zero-grace sweep inline without depending on the maintenance-queue worker.
The Celery task :func:`sweep_stuck_jobs` is the thin wrapper Celery beat
fires every minute, and uses the conservative defaults.
"""

from datetime import UTC, datetime, timedelta
from typing import TypedDict

import structlog
from rag_common.db import models
from rag_common.db.session import get_sessionmaker
from rag_common.enums import JobStatus
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rag_benchmarking.workers.celery_app import celery_app
from rag_benchmarking.workers.dispatch import dispatch_job

logger = structlog.get_logger(__name__)

# Defaults used by the scheduled Celery sweep. The operator-triggered sweep
# in the API route passes ``queued_grace_seconds=0`` to act immediately.
QUEUED_GRACE_SECONDS = 600
RUNNING_HEARTBEAT_SECONDS = 600
MAX_RETRIES = 3

# Only these AsyncResult states unambiguously mean the broker is no longer
# holding the task. We deliberately do NOT include "PENDING" — Celery returns
# PENDING both for "no record" and for "task is in the queue waiting for a
# worker". The stale queued recovery below handles long-lived PENDING task ids
# only after the DB row has had no heartbeat for the configured grace window.
_CERTAIN_DEAD_STATES = frozenset({"REVOKED", "FAILURE", "RETRY", "SUCCESS"})


class SweepReport(TypedDict):
    redispatched: int
    exhausted: int
    reaped: int


def _celery_task_is_dead(task_id: str | None) -> bool:
    if not task_id:
        return True
    state = celery_app.AsyncResult(task_id).state
    return state in _CERTAIN_DEAD_STATES


def _queued_job_is_stale(job: models.Job, now: datetime, queued_grace_seconds: int) -> bool:
    reference = job.last_heartbeat_at or job.created_at
    return reference < now - timedelta(seconds=queued_grace_seconds)


def _queued_job_needs_recovery(job: models.Job, now: datetime, queued_grace_seconds: int) -> bool:
    # A null task id proves dispatch never reached the broker, regardless of
    # how recently the row was inserted. Re-attempt on every sweep pass — the
    # operator-triggered sweep relies on this to recover jobs whose initial
    # apply_async raised because the broker was down.
    if not job.celery_task_id:
        return True
    if not _queued_job_is_stale(job, now, queued_grace_seconds):
        return False
    if _celery_task_is_dead(job.celery_task_id):
        return True
    # PENDING and STARTED can both be stale from the DB's perspective: the
    # task id exists, but no worker ever made the durable transition to
    # running. Once the grace window is exceeded, recover from the DB row.
    return True


def _revoke_existing_task(job: models.Job) -> None:
    if not job.celery_task_id:
        return
    try:
        celery_app.control.revoke(job.celery_task_id, terminate=True, signal="SIGTERM")
    except Exception:  # noqa: BLE001 — best-effort cleanup before redispatch
        logger.warning(
            "job_revoke_before_redispatch_failed",
            job_id=job.id,
            celery_task_id=job.celery_task_id,
            exc_info=True,
        )


def _collect_redispatch_candidates(session: Session, now: datetime, queued_grace_seconds: int) -> list[models.Job]:
    """Return queued rows that the sweeper should re-handle, holding row
    locks so a concurrent sweep cannot pick the same rows. The caller is
    responsible for the dispatch (potentially slow broker IO) and the final
    commit — keeping that work outside the SELECT FOR UPDATE bounds the lock
    hold time to a single SQL round-trip.

    The ``created_at <= cutoff`` filter is intentionally inclusive so a
    zero-grace sweep (``queued_grace_seconds=0``) picks up rows whose
    ``created_at`` equals ``now`` — without it, a freshly-inserted row
    created in the same instant as the sweep would be skipped.
    """
    cutoff = now - timedelta(seconds=queued_grace_seconds)
    stmt = (
        select(models.Job)
        .where(models.Job.status == JobStatus.QUEUED, models.Job.created_at <= cutoff)
        .order_by(models.Job.created_at)
        .with_for_update(skip_locked=True)
        .limit(50)
    )
    return [job for job in session.scalars(stmt) if _queued_job_needs_recovery(job, now, queued_grace_seconds)]


def _redispatch_queued(session: Session, now: datetime, queued_grace_seconds: int) -> tuple[int, int]:
    candidates = _collect_redispatch_candidates(session, now, queued_grace_seconds)
    redispatched = 0
    exhausted = 0
    for job in candidates:
        if job.retry_count >= MAX_RETRIES:
            job.status = JobStatus.FAILED
            job.error = f"retry budget exhausted after {job.retry_count} attempts"
            job.progress = 100
            job.current_step = "retry budget exhausted"
            job.completed_at = now
            job.last_heartbeat_at = now
            exhausted += 1
            logger.warning(
                "job_retry_budget_exhausted",
                job_id=job.id,
                retry_count=job.retry_count,
            )
            continue
        _revoke_existing_task(job)
        task_id = dispatch_job(job)
        job.retry_count += 1
        job.last_heartbeat_at = now
        if task_id is not None:
            job.celery_task_id = task_id
            redispatched += 1
            logger.info(
                "job_redispatched",
                job_id=job.id,
                retry_count=job.retry_count,
                celery_task_id=task_id,
            )
        else:
            logger.warning(
                "job_redispatch_broker_unavailable",
                job_id=job.id,
                retry_count=job.retry_count,
            )
    return redispatched, exhausted


def _reap_silent_runners(session: Session, now: datetime, heartbeat_seconds: int) -> int:
    cutoff = now - timedelta(seconds=heartbeat_seconds)
    stmt = (
        select(models.Job)
        .where(
            models.Job.status == JobStatus.RUNNING,
            models.Job.last_heartbeat_at.is_not(None),
            models.Job.last_heartbeat_at < cutoff,
        )
        .with_for_update(skip_locked=True)
        .limit(50)
    )
    reaped = 0
    for job in session.scalars(stmt):
        gap = now - (job.last_heartbeat_at or now)
        job.status = JobStatus.FAILED
        job.error = f"no heartbeat for {int(gap.total_seconds())}s"
        job.progress = 100
        job.current_step = "no heartbeat"
        job.completed_at = now
        reaped += 1
        logger.warning(
            "job_running_reaped",
            job_id=job.id,
            heartbeat_gap_seconds=int(gap.total_seconds()),
        )
    return reaped


def _diagnostic_counts(session: Session) -> dict[str, int]:
    """Snapshot status counters so even a no-op sweep emits useful telemetry.

    ``running_without_heartbeat`` is the smoking gun for the current
    debug session — a non-zero value here means rows are in ``running``
    yet ``_reap_silent_runners`` cannot see them (its WHERE clause requires
    ``last_heartbeat_at IS NOT NULL``).
    """
    queued = (
        session.scalar(select(func.count()).select_from(models.Job).where(models.Job.status == JobStatus.QUEUED)) or 0
    )
    running = (
        session.scalar(select(func.count()).select_from(models.Job).where(models.Job.status == JobStatus.RUNNING)) or 0
    )
    running_no_hb = (
        session.scalar(
            select(func.count())
            .select_from(models.Job)
            .where(models.Job.status == JobStatus.RUNNING, models.Job.last_heartbeat_at.is_(None))
        )
        or 0
    )
    return {
        "queued_jobs": queued,
        "running_jobs": running,
        "running_jobs_without_heartbeat": running_no_hb,
    }


def run_sweep(
    session: Session,
    *,
    now: datetime,
    queued_grace_seconds: int,
    heartbeat_seconds: int,
) -> SweepReport:
    """Execute a single sweep pass on ``session`` and return what changed.

    Does not commit — the caller owns the session lifecycle. Callers:

    - The Celery task :func:`sweep_stuck_jobs` (scheduled by beat) opens its
      own short-lived session and commits before returning.
    - The ``POST /v1/jobs/sweep`` route handler reuses the request-scoped
      session and commits at end of request.
    """
    redispatched, exhausted = _redispatch_queued(session, now, queued_grace_seconds)
    reaped = _reap_silent_runners(session, now, heartbeat_seconds)
    return {"redispatched": redispatched, "exhausted": exhausted, "reaped": reaped}


@celery_app.task(name="rag_benchmarking.sweep_stuck_jobs", bind=True, acks_late=True)
def sweep_stuck_jobs(self: object) -> SweepReport:
    """Scan for stranded jobs and recover them. Idempotent — safe to run often."""
    maker = get_sessionmaker()
    with maker() as session:
        now = datetime.now(UTC)
        report = run_sweep(
            session,
            now=now,
            queued_grace_seconds=QUEUED_GRACE_SECONDS,
            heartbeat_seconds=RUNNING_HEARTBEAT_SECONDS,
        )
        diagnostics = _diagnostic_counts(session)
        session.commit()
    logger.info(
        "sweep_pass_done",
        redispatched=report["redispatched"],
        exhausted=report["exhausted"],
        reaped=report["reaped"],
        **diagnostics,
    )
    return report
