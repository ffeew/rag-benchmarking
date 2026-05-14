import time

import structlog

from rag_benchmarking.db.session import get_sessionmaker
from rag_benchmarking.evaluation.runner import run_evaluation
from rag_benchmarking.ingestion.pipeline import run_document_ingestion
from rag_benchmarking.workers.celery_app import celery_app
from rag_benchmarking.workers.job_state import (
    commit_job_progress,
    record_job_failure,
)

__all__ = [
    "commit_job_progress",
    "ingest_document_task",
    "record_job_failure",
    "run_evaluation_task",
]

logger = structlog.get_logger(__name__)


def _format_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"


@celery_app.task(name="rag_benchmarking.ingest_document", bind=True, acks_late=True)
def ingest_document_task(self: object, *, document_id: str, job_id: str, force: bool = False) -> str:
    log = logger.bind(job_id=job_id, document_id=document_id, force=force)
    log.info("ingest_task_start")
    try:
        log.info("ingest_task_commit_running_start")
        commit_job_progress(
            job_id,
            status="running",
            progress=1,
            current_step="worker picked up",
        )
        log.info("ingest_task_commit_running_done")
        maker = get_sessionmaker()
        with maker() as session:
            log.info("ingest_task_pipeline_start")
            started = time.perf_counter()
            run = run_document_ingestion(
                session,
                document_id=document_id,
                job_id=job_id,
                force=force,
            )
            log.info(
                "ingest_task_pipeline_done",
                run_id=run.id,
                elapsed_seconds=round(time.perf_counter() - started, 3),
            )
            session.commit()
            log.info("ingest_task_commit_done", run_id=run.id)
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
        raise


@celery_app.task(name="rag_benchmarking.run_evaluation", bind=True, acks_late=True)
def run_evaluation_task(self: object, *, eval_run_id: str, job_id: str) -> str:
    log = logger.bind(job_id=job_id, eval_run_id=eval_run_id)
    log.info("eval_task_start")
    try:
        maker = get_sessionmaker()
        with maker() as session:
            started = time.perf_counter()
            eval_run = run_evaluation(session, eval_run_id=eval_run_id, job_id=job_id)
            log.info(
                "eval_task_pipeline_done",
                elapsed_seconds=round(time.perf_counter() - started, 3),
            )
            session.commit()
            log.info("eval_task_commit_done")
            return eval_run.id
    except Exception as exc:
        log.exception(
            "eval_task_failed",
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
        )
        try:
            record_job_failure(job_id, _format_error(exc))
        except Exception as record_exc:  # noqa: BLE001 — surface every failure path
            log.exception(
                "eval_task_record_failure_failed",
                exception_type=record_exc.__class__.__name__,
                exception_message=str(record_exc),
            )
        raise
