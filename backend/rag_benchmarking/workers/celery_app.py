import structlog
from celery import Celery, signals
from rag_common.config import get_settings
from rag_common.constants import (
    QUEUE_EVALUATION,
    QUEUE_INGESTION,
    QUEUE_MAINTENANCE,
    TASK_INGEST_DOCUMENT,
    TASK_RUN_EVALUATION,
    TASK_SWEEP_STUCK_JOBS,
)
from rag_common.logging import configure_logging

settings = get_settings()

# This Celery instance is shared by:
#   * the API + migrate images (producer-side: send_task, control.revoke).
#   * the scheduler / maintenance-worker image (consumer-side: registers the
#     sweeper task via `include`).
# The ingestion/evaluation tasks live in the `rag-ingestion-worker` package
# and are registered on a separate Celery app there — keeping them out of
# `include` here is what lets the lean images skip the heavy worker deps.
celery_app = Celery(
    "rag_benchmarking",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["rag_benchmarking.workers.sweeper"],
)

celery_app.conf.task_routes = {
    TASK_INGEST_DOCUMENT: {"queue": QUEUE_INGESTION},
    TASK_RUN_EVALUATION: {"queue": QUEUE_EVALUATION},
    TASK_SWEEP_STUCK_JOBS: {"queue": QUEUE_MAINTENANCE},
}
celery_app.conf.task_track_started = True

# Fault-tolerance settings — ensure messages survive worker crashes and that
# hung tasks cannot starve the queue forever. See docs/system-design.md for
# the rationale behind each value.
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.task_acks_on_failure_or_timeout = True
celery_app.conf.worker_prefetch_multiplier = 1
celery_app.conf.task_time_limit = 1800
celery_app.conf.task_soft_time_limit = 1500
celery_app.conf.broker_transport_options = {"visibility_timeout": 3600}
celery_app.conf.result_expires = 86400

# Beat schedule for the sweeper. Beat must be running as a separate process
# (see the `beat` service in docker-compose.yml) for these to fire.
celery_app.conf.beat_schedule = {
    "sweep-stuck-jobs": {
        "task": TASK_SWEEP_STUCK_JOBS,
        "schedule": 60.0,
    },
}


# Signal-driven logging setup + per-task lifecycle observability. Connecting a
# receiver to ``setup_logging`` tells Celery to skip its default logging
# initialization and trust our handler — without this our JSON formatter is
# stomped on by Celery's stdlib basicConfig at worker boot.
_log = structlog.get_logger(__name__)


def _configure_celery_logging(**_kwargs: object) -> None:
    configure_logging()


def _on_worker_process_init(**_kwargs: object) -> None:
    # Each prefork child needs its own logging handlers; ``setup_logging``
    # only fires in the main worker process.
    configure_logging()
    _log.info("worker_process_init")


def _on_task_prerun(
    task_id: str | None = None,
    task: object = None,
    args: object = None,
    kwargs: object = None,
    **_extras: object,
) -> None:
    _log.info(
        "task_prerun",
        task_id=task_id,
        task_name=getattr(task, "name", None),
        args=args,
        kwargs=kwargs,
    )


def _on_task_postrun(
    task_id: str | None = None,
    task: object = None,
    args: object = None,
    kwargs: object = None,
    retval: object = None,
    state: str | None = None,
    **_extras: object,
) -> None:
    _log.info(
        "task_postrun",
        task_id=task_id,
        task_name=getattr(task, "name", None),
        state=state,
        retval=repr(retval) if retval is not None else None,
    )


def _on_task_failure(
    task_id: str | None = None,
    exception: BaseException | None = None,
    args: object = None,
    kwargs: object = None,
    traceback: object = None,
    einfo: object = None,
    sender: object = None,
    **_extras: object,
) -> None:
    _log.error(
        "task_failure",
        task_id=task_id,
        task_name=getattr(sender, "name", None),
        exception_type=type(exception).__name__ if exception else None,
        exception_message=str(exception) if exception else None,
        traceback=str(einfo) if einfo is not None else None,
    )


def _on_task_retry(
    request: object = None,
    reason: object = None,
    einfo: object = None,
    sender: object = None,
    **_extras: object,
) -> None:
    _log.warning(
        "task_retry",
        task_id=getattr(request, "id", None),
        task_name=getattr(sender, "name", None),
        reason=str(reason) if reason is not None else None,
    )


def _on_task_revoked(
    *,
    request: object = None,
    terminated: bool | None = None,
    signum: int | None = None,
    expired: bool | None = None,
    sender: object = None,
    **_extras: object,
) -> None:
    _log.warning(
        "task_revoked",
        task_id=getattr(request, "id", None),
        task_name=getattr(sender, "name", None),
        terminated=terminated,
        signum=signum,
        expired=expired,
    )


signals.setup_logging.connect(_configure_celery_logging)
signals.worker_process_init.connect(_on_worker_process_init)
signals.task_prerun.connect(_on_task_prerun)
signals.task_postrun.connect(_on_task_postrun)
signals.task_failure.connect(_on_task_failure)
signals.task_retry.connect(_on_task_retry)
signals.task_revoked.connect(_on_task_revoked)
