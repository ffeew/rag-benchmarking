import time

import structlog
from rag_common.constants import TASK_INGEST_DOCUMENT
from rag_common.db.session import get_sessionmaker
from rag_common.enums import JobStatus
from rag_common.ingestion_run_state import record_ingestion_run_failure
from rag_common.job_state import (
    commit_job_progress,
    record_job_failure,
)

from rag_ingestion_worker.celery_app import celery_app
from rag_ingestion_worker.ingestion.pipeline import run_document_ingestion

__all__ = ["ingest_document_task"]

logger = structlog.get_logger(__name__)


def _format_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"


@celery_app.task(name=TASK_INGEST_DOCUMENT, bind=True, acks_late=True)
def ingest_document_task(self: object, *, document_id: str, job_id: str, force: bool = False) -> str:
    log = logger.bind(job_id=job_id, document_id=document_id, force=force)
    log.info("ingest_task_start")
    # Captured before session.commit() so a commit-time failure can still
    # mark the (already-bootstrapped) run row failed.
    run_id: str | None = None
    try:
        log.debug("ingest_task_commit_running_start")
        commit_job_progress(
            job_id,
            status=JobStatus.RUNNING,
            progress=1,
            current_step="worker picked up",
        )
        log.debug("ingest_task_commit_running_done")
        maker = get_sessionmaker()
        with maker() as session:
            log.debug("ingest_task_pipeline_start")
            started = time.perf_counter()
            run = run_document_ingestion(
                session,
                document_id=document_id,
                job_id=job_id,
                force=force,
            )
            run_id = run.id
            log.debug(
                "ingest_task_pipeline_done",
                run_id=run.id,
                elapsed_seconds=round(time.perf_counter() - started, 3),
            )
            session.commit()
            log.debug("ingest_task_commit_done", run_id=run.id)
            return run.id
    except Exception as exc:
        log.exception(
            "ingest_task_failed",
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
        )
        try:
            record_job_failure(job_id, _format_error(exc))
        except Exception as record_exc:  # noqa: BLE001 — surface every failure path
            log.exception(
                "ingest_task_record_failure_failed",
                exception_type=record_exc.__class__.__name__,
                exception_message=str(record_exc),
            )
        try:
            record_ingestion_run_failure(run_id, _format_error(exc))
        except Exception as record_exc:  # noqa: BLE001 — surface every failure path
            log.exception(
                "ingest_task_record_run_failure_failed",
                exception_type=record_exc.__class__.__name__,
                exception_message=str(record_exc),
            )
        raise
