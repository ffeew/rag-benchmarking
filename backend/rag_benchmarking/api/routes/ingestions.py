from fastapi import APIRouter, HTTPException, status
from rag_common.db import models
from rag_common.schemas import IngestionCreate, IngestionCreateResponse, IngestionRunRead
from sqlalchemy import select

from rag_benchmarking.api.deps import AuthDep, DbSession
from rag_benchmarking.api.serialization import ingestion_run_to_read
from rag_benchmarking.ingestion.queueing import queue_ingestion_jobs

router = APIRouter(tags=["ingestions"])


@router.get("/v1/datasets/{dataset_id}/ingestion-runs")
def list_ingestion_runs(
    dataset_id: str,
    session: DbSession,
    _auth: AuthDep,
) -> list[IngestionRunRead]:
    dataset = session.get(models.Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    statement = (
        select(models.IngestionRun)
        .where(models.IngestionRun.dataset_id == dataset_id)
        .order_by(models.IngestionRun.created_at.desc())
    )
    return [ingestion_run_to_read(run) for run in session.scalars(statement)]


@router.post("/v1/datasets/{dataset_id}/ingestions")
def create_ingestion(
    dataset_id: str,
    payload: IngestionCreate,
    session: DbSession,
    _auth: AuthDep,
) -> IngestionCreateResponse:
    dataset = session.get(models.Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    statement = select(models.Document).where(models.Document.dataset_id == dataset_id)
    if payload.document_ids:
        statement = statement.where(models.Document.id.in_(payload.document_ids))
    if payload.minio_prefix:
        statement = statement.where(models.Document.minio_key.startswith(payload.minio_prefix))
    documents = list(session.scalars(statement.order_by(models.Document.ticker, models.Document.filing_date)))

    result = queue_ingestion_jobs(
        session,
        dataset_id=dataset_id,
        documents=documents,
        force=payload.force,
    )
    return IngestionCreateResponse(
        job_ids=result.job_ids,
        queued_document_ids=result.queued_document_ids,
        skipped_document_ids=result.skipped_document_ids,
        broker_unavailable_document_ids=result.broker_unavailable_document_ids,
    )
