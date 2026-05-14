from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from rag_common.db import models
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_benchmarking.workers.dispatch import dispatch_job

ACTIVE_INGESTION_JOB_STATUSES = frozenset({"queued", "running"})

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IngestionQueueResult:
    job_ids: list[str]
    queued_document_ids: list[str]
    skipped_document_ids: list[str]


def has_active_ingestion_job(session: Session, document_id: str) -> bool:
    job_id = session.scalar(
        select(models.Job.id)
        .where(
            models.Job.job_type == "ingestion",
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
        if not should_queue_ingestion(session, document, force=force):
            skipped_document_ids.append(document.id)
            logger.info(
                "ingestion_queue_document_skipped",
                dataset_id=dataset_id,
                document_id=document.id,
            )
            continue

        job = models.Job(
            job_type="ingestion",
            status="queued",
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
    )
