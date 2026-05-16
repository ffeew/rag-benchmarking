import time

import structlog
from rag_common.constants import TASK_RUN_EVALUATION
from rag_common.db import models
from rag_common.db.session import get_sessionmaker
from rag_common.enums import JOB_TERMINAL_STATUSES, JobStatus
from rag_common.job_state import record_job_failure

from rag_evaluation_worker.celery_app import celery_app
from rag_evaluation_worker.runner import run_evaluation

__all__ = ["run_evaluation_task"]

logger = structlog.get_logger(__name__)


def _format_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"


def _record_eval_run_failure(eval_run_id: str, exc: Exception) -> None:
    """Persist a FAILED status onto the EvalRun in its own session.

    The runner's session is unusable after a crash, so this opens a fresh
    transaction. Refuses to overwrite a terminal status so a runner-set
    ``completed_with_errors`` is preserved.
    """
    maker = get_sessionmaker()
    with maker() as session:
        run = session.get(models.EvalRun, eval_run_id)
        if run is None:
            return
        if run.status in JOB_TERMINAL_STATUSES:
            return
        run.status = JobStatus.FAILED
        run.errors = list(run.errors or []) + [
            {
                "case_id": None,
                "variant": None,
                "error_class": type(exc).__name__,
                "error": _format_error(exc),
            }
        ]
        session.commit()


@celery_app.task(name=TASK_RUN_EVALUATION, bind=True, acks_late=True)
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
            _record_eval_run_failure(eval_run_id, exc)
        except Exception as record_exc:  # noqa: BLE001 — surface every failure path
            log.exception(
                "eval_task_record_eval_run_failure_failed",
                exception_type=record_exc.__class__.__name__,
                exception_message=str(record_exc),
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
