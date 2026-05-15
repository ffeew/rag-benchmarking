"""Periodic query-trace retention.

Deletes ``QueryTrace`` rows older than ``query_trace_retention_days`` that
are not referenced by any ``EvalResult``. Traces tied to an eval result are
preserved so evaluation reproducibility is intact — the FK uses
``ondelete="SET NULL"`` but the orphan-only filter avoids relying on it.

The work is split exactly like ``sweeper``: ``run_trace_retention`` takes a
session and returns a report (no commit, callable from a request handler),
and the Celery task wrapper opens its own short-lived session and commits.
"""

from datetime import UTC, datetime, timedelta
from typing import TypedDict

import structlog
from rag_common.config import get_settings
from rag_common.db import models
from rag_common.db.session import get_sessionmaker
from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from rag_benchmarking.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)

# Bound per-pass work so the first run after a long gap can't lock the table
# for minutes. Subsequent beat passes pick up the remainder.
RETENTION_BATCH_LIMIT = 500


class RetentionReport(TypedDict):
    deleted: int
    cutoff_iso: str


def run_trace_retention(
    session: Session,
    *,
    now: datetime,
    retention_days: int,
    batch_limit: int = RETENTION_BATCH_LIMIT,
) -> RetentionReport:
    """Delete one batch of orphan traces older than the cutoff.

    Does not commit — the caller owns the session lifecycle, matching the
    sweeper convention so the same helper can be reused from an inline API
    handler if one is added later.

    "Orphan" means no ``EvalResult.trace_id`` references the trace. The
    ``Citation`` rows pointing at the trace cascade away via the FK definition.
    """
    cutoff = now - timedelta(days=retention_days)
    referenced_subq = (
        select(models.EvalResult.id)
        .where(models.EvalResult.trace_id == models.QueryTrace.id)
        .correlate(models.QueryTrace)
    )
    # Lock a batch of orphan IDs first so a concurrent pass can't pick the
    # same rows, then issue a bulk DELETE for the locked set. Using a bulk
    # DELETE (rather than ``session.delete(trace)`` in a loop) sidesteps the
    # ORM unit-of-work cascade — which would try to NULL ``Citation.trace_id``
    # and fail its NOT NULL constraint — and lets the DB-level FK
    # ``ondelete="CASCADE"`` on Citation handle the dependents instead.
    id_stmt = (
        select(models.QueryTrace.id)
        .where(
            models.QueryTrace.created_at < cutoff,
            ~exists(referenced_subq),
        )
        .order_by(models.QueryTrace.created_at)
        .with_for_update(skip_locked=True)
        .limit(batch_limit)
    )
    trace_ids = list(session.scalars(id_stmt))
    if trace_ids:
        session.execute(
            delete(models.QueryTrace)
            .where(models.QueryTrace.id.in_(trace_ids))
            .execution_options(synchronize_session=False),
        )
    return {"deleted": len(trace_ids), "cutoff_iso": cutoff.isoformat()}


# Literal task name (must match ``TASK_PURGE_OLD_TRACES`` in
# ``rag_common.constants``). The producer side imports the constant; this
# consumer-side decorator uses the string directly so the celery_app.task
# call has a fully typed signature for mypy.
@celery_app.task(name="rag_benchmarking.purge_old_traces", bind=True, acks_late=True)
def purge_old_traces(self: object) -> RetentionReport:
    """Scheduled retention pass. Idempotent — safe to run on every beat tick."""
    settings = get_settings()
    retention_days = settings.query_trace_retention_days
    maker = get_sessionmaker()
    with maker() as session:
        now = datetime.now(UTC)
        report = run_trace_retention(session, now=now, retention_days=retention_days)
        session.commit()
    logger.info(
        "trace_retention_pass_done",
        deleted=report["deleted"],
        retention_days=retention_days,
        cutoff_iso=report["cutoff_iso"],
    )
    return report
