from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from rag_common.db import models
from rag_common.enums import JobStatus, JobType
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_benchmarking.workers.dispatch import dispatch_job

ACTIVE_INGESTION_JOB_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IngestionQueueResult:
    job_ids: list[str]
    queued_document_ids: list[str]
    skipped_document_ids: list[str]
    # Job rows that landed in the DB but the broker (Redis) refused the dispatch.
    # The sweeper will pick them up on its next pass; surface them so callers can
    # show "queued, broker unavailable — will be retried" instead of a silent 200.
    broker_unavailable_document_ids: list[str]


def has_active_ingestion_job(session: Session, document_id: str) -> bool:
    job_id = session.scalar(
        select(models.Job.id)
        .where(
            models.Job.job_type == JobType.INGESTION,
            models.Job.document_id == document_id,
            models.Job.status.in_(ACTIVE_INGESTION_JOB_STATUSES),
        )
        .limit(1)
    )
    return job_id is not None


def should_queue_ingestion(session: Session, document: models.Document, *, force: bool) -> bool:
    if force:
        return True
    if document.active_ingestion_run_id:
        return False
    return not has_active_ingestion_job(session, document.id)


def queue_ingestion_jobs(
    session: Session,
    *,
    dataset_id: str,
    documents: Sequence[models.Document],
    force: bool,
) -> IngestionQueueResult:
    job_ids: list[str] = []
    queued_document_ids: list[str] = []
    skipped_document_ids: list[str] = []
    broker_unavailable_document_ids: list[str] = []
    seen_document_ids: set[str] = set()
    committed = False
    logger.info(
        "ingestion_queue_batch_start",
        dataset_id=dataset_id,
        document_count=len(documents),
        force=force,
    )

    for document in documents:
        if document.id in seen_document_ids:
            continue
        seen_document_ids.add(document.id)
        # Lock the document row for the duration of the active-job check so two
        # concurrent POSTs to /ingestions cannot both observe "no active job"
        # and race-insert duplicate Jobs for the same document.
        locked = session.get(models.Document, document.id, with_for_update=True)
        if locked is None:
            continue
        if not should_queue_ingestion(session, locked, force=force):
            skipped_document_ids.append(document.id)
            logger.info(
                "ingestion_queue_document_skipped",
                dataset_id=dataset_id,
                document_id=document.id,
            )
            continue

        job = models.Job(
            job_type=JobType.INGESTION,
            status=JobStatus.QUEUED,
            progress=0,
            current_step="queued",
            dataset_id=dataset_id,
            document_id=document.id,
            metadata_={"force": force},
        )
        session.add(job)
        session.commit()
        committed = True
        logger.info(
            "ingestion_queue_job_created",
            job_id=job.id,
            dataset_id=dataset_id,
            document_id=document.id,
            force=force,
        )

        task_id = dispatch_job(job)
        logger.info(
            "ingestion_queue_dispatch_done",
            job_id=job.id,
            document_id=document.id,
            celery_task_id=task_id,
            broker_accepted=task_id is not None,
        )
        if task_id is not None:
            job.celery_task_id = task_id
            session.commit()
            committed = True
        else:
            broker_unavailable_document_ids.append(document.id)

        job_ids.append(job.id)
        queued_document_ids.append(document.id)

    if not committed:
        session.commit()

    logger.info(
        "ingestion_queue_batch_summary",
        dataset_id=dataset_id,
        queued=len(queued_document_ids),
        skipped=len(skipped_document_ids),
    )
    return IngestionQueueResult(
        job_ids=job_ids,
        queued_document_ids=queued_document_ids,
        skipped_document_ids=skipped_document_ids,
        broker_unavailable_document_ids=broker_unavailable_document_ids,
    )
