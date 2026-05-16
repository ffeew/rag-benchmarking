from rag_common.db import models
from rag_common.schemas import (
    CitationRead,
    DatasetRead,
    DocumentRead,
    EvalResultRead,
    EvalRunRead,
    JobRead,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ACTIVE_INGESTION_JOB_STATUSES = frozenset({"queued", "running"})


def dataset_to_read(session: Session, dataset: models.Dataset) -> DatasetRead:
    document_count = session.scalar(
        select(func.count()).select_from(models.Document).where(models.Document.dataset_id == dataset.id)
    )
    chunk_count = session.scalar(
        select(func.count())
        .select_from(models.Chunk)
        .join(models.Document, models.Document.id == models.Chunk.document_id)
        .where(models.Document.dataset_id == dataset.id, models.Chunk.is_active.is_(True))
    )
    completed_count = session.scalar(
        select(func.count())
        .select_from(models.IngestionRun)
        .where(models.IngestionRun.dataset_id == dataset.id, models.IngestionRun.status == "completed")
    )
    return DatasetRead(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        default_query_settings=dataset.default_query_settings,
        domain_label=dataset.domain_label,
        entity_label=dataset.entity_label,
        valid_forms=dataset.valid_forms,
        metric_terms=dataset.metric_terms,
        hyde_style_hint=dataset.hyde_style_hint,
        citation_label_template=dataset.citation_label_template,
        created_at=dataset.created_at,
        document_count=document_count or 0,
        active_chunk_count=chunk_count or 0,
        completed_ingestion_count=completed_count or 0,
    )


def document_to_read(session: Session, document: models.Document) -> DocumentRead:
    ingestion_status = session.scalar(
        select(models.Job.status)
        .where(
            models.Job.job_type == "ingestion",
            models.Job.document_id == document.id,
            models.Job.status.in_(ACTIVE_INGESTION_JOB_STATUSES),
        )
        .order_by(models.Job.created_at.desc())
        .limit(1)
    )
    if ingestion_status is None and document.active_ingestion_run_id:
        ingestion_status = session.scalar(
            select(models.IngestionRun.status).where(models.IngestionRun.id == document.active_ingestion_run_id)
        )
    if ingestion_status is None:
        ingestion_status = session.scalar(
            select(models.IngestionRun.status)
            .where(models.IngestionRun.document_id == document.id)
            .order_by(models.IngestionRun.created_at.desc())
            .limit(1)
        )
    return DocumentRead(
        id=document.id,
        dataset_id=document.dataset_id,
        ticker=document.ticker,
        company_name=document.company_name,
        form_type=document.form_type,
        filing_date=document.filing_date,
        report_period=document.report_period,
        fiscal_year=document.fiscal_year,
        fiscal_quarter=document.fiscal_quarter,
        checksum=document.checksum,
        minio_bucket=document.minio_bucket,
        minio_key=document.minio_key,
        minio_version_id=document.minio_version_id,
        byte_size=document.byte_size,
        active_ingestion_run_id=document.active_ingestion_run_id,
        ingestion_status=ingestion_status,
        created_at=document.created_at,
    )


def job_to_read(job: models.Job) -> JobRead:
    return JobRead(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        dataset_id=job.dataset_id,
        document_id=job.document_id,
        eval_run_id=job.eval_run_id,
        error=job.error,
        metadata=job.metadata_,
        started_at=job.started_at,
        completed_at=job.completed_at,
        last_heartbeat_at=job.last_heartbeat_at,
        retry_count=job.retry_count,
        created_at=job.created_at,
    )


def citation_to_read(citation: models.Citation, document: models.Document) -> CitationRead:
    return CitationRead(
        document_id=document.id,
        ticker=document.ticker,
        form_type=document.form_type,
        filing_date=document.filing_date,
        report_period=document.report_period,
        page_number=citation.page_number,
        chunk_id=citation.chunk_id,
        minio_bucket=citation.minio_bucket,
        minio_key=citation.minio_key,
        minio_version_id=citation.minio_version_id,
        snippet=citation.evidence_text,
        label=citation.citation_label,
    )


def eval_run_to_read(eval_run: models.EvalRun) -> EvalRunRead:
    return EvalRunRead(
        id=eval_run.id,
        dataset_id=eval_run.dataset_id,
        job_id=eval_run.job_id,
        status=eval_run.status,
        run_config=eval_run.run_config,
        system_variant=eval_run.system_variant,
        model_metadata=eval_run.model_metadata,
        metrics=eval_run.metrics,
        errors=eval_run.errors,
        created_at=eval_run.created_at,
        results=[
            EvalResultRead(
                id=result.id,
                eval_case_id=result.eval_case_id,
                retrieval_mode=result.retrieval_mode,
                variant_name=result.variant_name,
                answer=result.answer,
                trace_id=result.trace_id,
                metrics=result.metrics,
                error=result.error,
                usage=result.usage,
                cost_estimate=result.cost_estimate,
                latency_ms=result.latency_ms,
            )
            for result in eval_run.results
        ],
    )
