"""In-process evaluation launcher.

This module replaces the old ``rag_evaluation.tasks.run_evaluation_task``
Celery task. Instead of dispatching a message to a separate worker container,
the API and CLI hand the persisted ``EvalRun`` / ``Job`` rows to
``launch_evaluation_thread`` which spawns a daemon thread inside the current
process. The thread opens its own SQLAlchemy session and calls
``rag_evaluation.runner.run_evaluation`` — exactly what the worker did,
without the broker hop.

Concurrency is bounded by a module-level semaphore sized from
``settings.eval_max_inflight`` (default 1, matching the previous Celery
worker's ``worker_prefetch_multiplier=1``).

``_INFLIGHT`` and the semaphore are per-process. The stuck-job sweeper
runs inline against the same API process via ``POST /v1/jobs/sweep``, so
the registry lookup ``inproc_thread_alive`` is always meaningful.
"""

import threading
import time
import uuid

import structlog
from rag_common.config import get_settings
from rag_common.db import models
from rag_common.db.session import get_sessionmaker
from rag_common.enums import JOB_TERMINAL_STATUSES, JobStatus
from rag_common.job_state import record_job_failure
from rag_evaluation.runner import run_evaluation

logger = structlog.get_logger(__name__)

INPROC_TASK_PREFIX = "inproc:"

_INFLIGHT: dict[str, threading.Thread] = {}
_INFLIGHT_LOCK = threading.Lock()

_SEMAPHORE = threading.BoundedSemaphore(get_settings().eval_max_inflight)


def is_inproc_task_id(task_id: str | None) -> bool:
    return task_id is not None and task_id.startswith(INPROC_TASK_PREFIX)


def inproc_thread_alive(task_id: str | None) -> bool:
    """Return ``True`` iff ``task_id`` refers to a thread that's still alive
    in *this* process.

    Returns ``False`` for task ids tracked by a different process — callers
    that need cross-process liveness should fall back to heartbeat staleness.
    """
    if task_id is None or not is_inproc_task_id(task_id):
        return False
    with _INFLIGHT_LOCK:
        thread = _INFLIGHT.get(task_id)
    return thread is not None and thread.is_alive()


def launch_evaluation_thread(*, eval_run_id: str, job_id: str) -> str:
    """Start a daemon thread that runs the evaluation and return a sentinel
    task id of the form ``inproc:eval-<eval_run_id>-<rand6>``.

    The thread acquires ``_SEMAPHORE`` before doing any work, so the DB row
    stays at ``QUEUED`` (with the sentinel task id already written by the
    caller) until a slot opens. Once acquired, the runner flips the row to
    ``RUNNING`` on its first commit (see ``run_evaluation`` line 758).
    """
    thread_name = f"eval-{eval_run_id}-{uuid.uuid4().hex[:6]}"
    task_id = f"{INPROC_TASK_PREFIX}{thread_name}"
    thread = threading.Thread(
        target=_run_in_thread,
        name=thread_name,
        kwargs={"eval_run_id": eval_run_id, "job_id": job_id, "task_id": task_id},
        daemon=True,
    )
    with _INFLIGHT_LOCK:
        _INFLIGHT[task_id] = thread
    thread.start()
    logger.info(
        "eval_thread_launched",
        eval_run_id=eval_run_id,
        job_id=job_id,
        task_id=task_id,
    )
    return task_id


def _run_in_thread(*, eval_run_id: str, job_id: str, task_id: str) -> None:
    log = logger.bind(job_id=job_id, eval_run_id=eval_run_id, task_id=task_id)
    log.info("eval_thread_waiting_semaphore")
    try:
        with _SEMAPHORE:
            log.info("eval_thread_start")
            try:
                maker = get_sessionmaker()
                with maker() as session:
                    started = time.perf_counter()
                    run_evaluation(session, eval_run_id=eval_run_id, job_id=job_id)
                    log.info(
                        "eval_thread_pipeline_done",
                        elapsed_seconds=round(time.perf_counter() - started, 3),
                    )
                    session.commit()
                    log.info("eval_thread_commit_done")
            except Exception as exc:
                log.exception(
                    "eval_thread_failed",
                    exception_type=exc.__class__.__name__,
                    exception_message=str(exc),
                )
                try:
                    _record_eval_run_failure(eval_run_id, exc)
                except Exception as record_exc:  # noqa: BLE001 — surface every failure path
                    log.exception(
                        "eval_thread_record_eval_run_failure_failed",
                        exception_type=record_exc.__class__.__name__,
                        exception_message=str(record_exc),
                    )
                try:
                    record_job_failure(job_id, _format_error(exc))
                except Exception as record_exc:  # noqa: BLE001 — surface every failure path
                    log.exception(
                        "eval_thread_record_failure_failed",
                        exception_type=record_exc.__class__.__name__,
                        exception_message=str(record_exc),
                    )
    finally:
        with _INFLIGHT_LOCK:
            _INFLIGHT.pop(task_id, None)


def _format_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"


def _record_eval_run_failure(eval_run_id: str, exc: Exception) -> None:
    """Persist a FAILED status onto the EvalRun in its own session.

    The thread's main session is unusable after a crash, so this opens a
    fresh transaction. Refuses to overwrite a terminal status so a
    runner-set ``completed_with_errors`` is preserved.
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
