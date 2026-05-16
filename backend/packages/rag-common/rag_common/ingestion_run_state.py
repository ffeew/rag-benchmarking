"""IngestionRun state writes that bypass the worker's main session.

Mirror of ``job_state.py`` for ``ingestion_runs``. The worker's primary
session holds uncommitted ``ParsedPage`` / ``Chunk`` / ``Embedding`` writes
for the entire pipeline; if the pipeline raises, the main session rolls
back and the ``IngestionRun`` row goes with it — leaving operators with a
``failed`` ``Job`` and no record of which run-config was tried or why it
broke. This helper writes on a fresh transaction so a failed run surfaces
durably.

Row lock is ``FOR KEY SHARE`` matching ``job_state.py`` — the helper only
needs to serialize against actors stronger than itself, and the share lock
is compatible with the FK-induced share locks parsed pages and chunks may
have already taken on the run row via their foreign key.

See also: ``rag_common.job_state`` for the analogous helper that protects
``Job`` rows.
"""

from datetime import UTC, datetime

import structlog

from rag_common.db import models
from rag_common.db.session import get_sessionmaker

TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "skipped"})

logger = structlog.get_logger(__name__)


def record_ingestion_run_failure(run_id: str | None, error: str) -> None:
    """Mark an IngestionRun row failed on its own transaction.

    No-op when ``run_id`` is None — the pipeline may raise before the run
    row is created (e.g. document not found), in which case there is
    nothing to update and ``Job`` failure recording carries the signal.
    Preserves existing terminal statuses (``completed`` / ``skipped``) so a
    late helper call cannot clobber a real outcome.
    """
    if run_id is None:
        return
    log = logger.bind(run_id=run_id)
    log.info("record_ingestion_run_failure_called", error=error[:500])
    maker = get_sessionmaker()
    try:
        with maker() as session:
            run = session.get(models.IngestionRun, run_id, with_for_update={"key_share": True})
            if run is None:
                log.warning("record_ingestion_run_failure_missing")
                return
            if run.status in TERMINAL_RUN_STATUSES:
                log.info("record_ingestion_run_failure_skipped_terminal", existing_status=run.status)
                return
            run.status = "failed"
            run.error_summary = error[:8000]
            run.timings = {**(run.timings or {}), "failed_at": datetime.now(UTC).isoformat()}
            session.commit()
            log.info("record_ingestion_run_failure_committed")
    except Exception as exc:
        # Intentionally swallow — the caller is already in an ``except``
        # re-raise chain handling the original pipeline failure. Surfacing
        # a DB error here would shadow the real exception in Celery's
        # failure log.
        log.exception(
            "record_ingestion_run_failure_db_error",
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
        )
