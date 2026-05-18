"""Periodic stuck-job sweeper.

Re-dispatches queued rows whose execution demonstrably vanished and fails
running rows that stopped emitting heartbeats. The DB is the source of
truth for what needs to run — this task closes the loop between persisted
intent and runtime reality (Celery broker for ingestion, in-process thread
for evaluation).

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
from rag_common.enums import JOB_TERMINAL_STATUSES, JobStatus
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rag_benchmarking.evaluation import inproc_thread_alive, is_inproc_task_id
from rag_benchmarking.workers.celery_app import celery_app
from rag_benchmarking.workers.dispatch import dispatch_job

logger = structlog.get_logger(__name__)

# Module-level defaults used by callers that don't have a Settings handy
# (e.g. legacy callers). The scheduled sweep and the operator-triggered route
# now read live values from ``rag_common.config.get_settings()`` so the
# thresholds are tunable via env without a code change.
QUEUED_GRACE_SECONDS = 600
RUNNING_HEARTBEAT_SECONDS = 2700
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
    if is_inproc_task_id(task_id):
        # Same-process introspection only — when sweep runs in a different
        # process from the launcher, the registry returns False (not alive).
        # The caller's heartbeat staleness check is the real liveness gate
        # for cross-process in-proc evals.
        return not inproc_thread_alive(task_id)
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
    if is_inproc_task_id(job.celery_task_id):
        # In-process evals can't be revoked via the broker — the daemon
        # thread either already exited (so the registry is empty) or is
        # still running in its own process. Cross-process termination
        # would require os-level signalling we don't want. The new task
        # id we're about to mint replaces the old one in the DB.
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


def _fail_linked_eval_run(session: Session, job: models.Job, *, now: datetime, reason: str) -> None:
    """Sync an evaluation Job's terminal failure onto its linked EvalRun.

    The runner's main session may have died holding uncommitted ``EvalRun``
    writes, leaving the row at its bootstrap ``queued`` value even though the
    Job has been ruled dead by the sweeper. Without this reconciliation the
    UI keeps polling a row that will never advance.

    Skips the write if the EvalRun is already terminal (e.g. the worker
    actually finished after the heartbeat lapse) so a real completion is not
    clobbered.

    Also enumerates ``(case_id, variant)`` pairs that some variants ran but
    others didn't (the typical reap pattern, since the runner loops cases
    outside variants) and emits one ``JobReaped`` error row per gap so the UI
    error table tells the operator which cells were dropped.
    """
    if not job.eval_run_id:
        return
    eval_run = session.get(models.EvalRun, job.eval_run_id, with_for_update={"key_share": True})
    if eval_run is None:
        return
    if eval_run.status in JOB_TERMINAL_STATUSES:
        return
    eval_run.status = JobStatus.FAILED
    new_errors: list[dict[str, object]] = [
        {
            "case_id": None,
            "variant": None,
            "error_class": "JobReaped",
            "error": reason,
            "reaped_at": now.isoformat(),
        }
    ]
    new_errors.extend(_reaped_per_variant_errors(eval_run, now=now))
    eval_run.errors = list(eval_run.errors or []) + new_errors


def _reaped_per_variant_errors(eval_run: models.EvalRun, *, now: datetime) -> list[dict[str, object]]:
    """Find (case, variant) cells that some variants completed but others
    skipped, and synthesise one error row per missing cell. Heuristic: the
    union of case_ids across variants is the "expected" set for this run.
    Cases that no variant ever started are invisible here — they need the
    dataset-side case list to enumerate, which the sweeper doesn't have."""
    results = getattr(eval_run, "results", None) or []
    by_variant: dict[str, set[str]] = {}
    for result in results:
        bucket = result.variant_name or result.retrieval_mode
        if not bucket or not result.eval_case_id:
            continue
        by_variant.setdefault(bucket, set()).add(result.eval_case_id)
    if not by_variant:
        return []
    expected_cases: set[str] = set().union(*by_variant.values())
    rows: list[dict[str, object]] = []
    for variant, case_ids in sorted(by_variant.items()):
        for missing_case in sorted(expected_cases - case_ids):
            rows.append(
                {
                    "case_id": missing_case,
                    "variant": variant,
                    "error_class": "JobReaped",
                    "error": "skipped (job reaped before reaching this case)",
                    "reaped_at": now.isoformat(),
                }
            )
    return rows


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
            _fail_linked_eval_run(session, job, now=now, reason=job.error)
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
        _fail_linked_eval_run(session, job, now=now, reason=job.error)
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
    from rag_common.config import get_settings

    settings = get_settings()
    maker = get_sessionmaker()
    with maker() as session:
        now = datetime.now(UTC)
        report = run_sweep(
            session,
            now=now,
            queued_grace_seconds=settings.queued_grace_seconds,
            heartbeat_seconds=settings.running_heartbeat_seconds,
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
