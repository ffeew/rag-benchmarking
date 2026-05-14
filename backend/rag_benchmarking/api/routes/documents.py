from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from rag_common.db import models
from rag_common.schemas import (
    DocumentRead,
    DocumentUploadResponse,
    Page,
    RegisterDocumentsResponse,
    RegisterLocalCorpusRequest,
)
from sqlalchemy import or_, select

from rag_benchmarking.api.deps import AuthDep, DbSession, SettingsDep
from rag_benchmarking.api.pagination import LimitParam, OffsetParam, paged_query
from rag_benchmarking.api.serialization import dataset_to_read, document_to_read
from rag_benchmarking.ingestion.documents import (
    register_local_corpus,
    register_pdf_path,
)
from rag_benchmarking.ingestion.queueing import queue_ingestion_jobs

type UploadedPdfFiles = Annotated[list[UploadFile], File(...)]

router = APIRouter(tags=["documents"])


@router.post("/v1/datasets/register-local-corpus")
def register_local_corpus_endpoint(
    payload: RegisterLocalCorpusRequest,
    session: DbSession,
    settings: SettingsDep,
    _auth: AuthDep,
) -> RegisterDocumentsResponse:
    dataset, documents, created, reused = register_local_corpus(
        session,
        dataset_name=payload.dataset_name,
        description=payload.description,
        path=Path(payload.path) if payload.path else None,
        settings=settings,
    )
    queue_result = queue_ingestion_jobs(
        session,
        dataset_id=dataset.id,
        documents=documents,
        force=False,
    )
    return RegisterDocumentsResponse(
        dataset=dataset_to_read(session, dataset),
        documents=[document_to_read(session, document) for document in documents],
        created_count=created,
        reused_count=reused,
        job_ids=queue_result.job_ids,
        queued_document_ids=queue_result.queued_document_ids,
        skipped_document_ids=queue_result.skipped_document_ids,
    )


@router.post("/v1/datasets/{dataset_id}/documents")
def upload_documents(
    dataset_id: str,
    files: UploadedPdfFiles,
    session: DbSession,
    settings: SettingsDep,
    _auth: AuthDep,
) -> DocumentUploadResponse:
    dataset = session.get(models.Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    documents: list[models.Document] = []
    with TemporaryDirectory(prefix="rag-upload-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        for file in files:
            if not file.filename or not file.filename.lower().endswith(".pdf"):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF uploads are supported")
            path = temp_dir / Path(file.filename).name
            path.write_bytes(file.file.read())
            document, _ = register_pdf_path(session, dataset=dataset, path=path, settings=settings)
            documents.append(document)
    queue_result = queue_ingestion_jobs(
        session,
        dataset_id=dataset_id,
        documents=documents,
        force=False,
    )
    return DocumentUploadResponse(
        documents=[document_to_read(session, document) for document in documents],
        job_ids=queue_result.job_ids,
        queued_document_ids=queue_result.queued_document_ids,
        skipped_document_ids=queue_result.skipped_document_ids,
    )


@router.get("/v1/datasets/{dataset_id}/documents")
def list_documents(
    dataset_id: str,
    session: DbSession,
    _auth: AuthDep,
    ticker: str | None = None,
    form_type: str | None = None,
    ingestion_status: str | None = None,
    q: str | None = None,
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
) -> Page[DocumentRead]:
    dataset = session.get(models.Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    base = select(models.Document).where(models.Document.dataset_id == dataset_id)
    if ticker:
        base = base.where(models.Document.ticker == ticker)
    if form_type:
        base = base.where(models.Document.form_type == form_type)
    if q:
        like = f"%{q}%"
        base = base.where(
            or_(
                models.Document.ticker.ilike(like),
                models.Document.company_name.ilike(like),
                models.Document.form_type.ilike(like),
                models.Document.minio_key.ilike(like),
            )
        )
    ordered = base.order_by(models.Document.ticker, models.Document.form_type, models.Document.filing_date.desc())
    rows, total = paged_query(session, base=base, ordered=ordered, limit=limit, offset=offset)
    items = [document_to_read(session, document) for document in rows]
    # ingestion_status is computed by document_to_read (joined from Job/IngestionRun),
    # not a column on Document, so filter after serialization. `total` reflects only
    # the SQL-level filters above — known v1 limitation.
    if ingestion_status:
        items = [d for d in items if (d.ingestion_status or "new") == ingestion_status]
    return Page[DocumentRead](items=items, total=total, limit=limit, offset=offset)
