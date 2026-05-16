from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from rag_common.db import models
from rag_common.schemas import (
    DocumentExtracted,
    DocumentRead,
    DocumentUpdate,
    DocumentUploadResponse,
    Page,
    ParsedPageRead,
    RegisterDocumentsResponse,
    RegisterLocalCorpusRequest,
)
from rag_common.storage.minio import ObjectStore
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
        domain_label=payload.domain_label,
        entity_label=payload.entity_label,
        valid_forms=payload.valid_forms,
        metric_terms=payload.metric_terms,
        hyde_style_hint=payload.hyde_style_hint,
        citation_label_template=payload.citation_label_template,
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


@router.patch("/v1/documents/{document_id}")
def update_document(
    document_id: str,
    payload: DocumentUpdate,
    session: DbSession,
    _auth: AuthDep,
) -> DocumentRead:
    document = session.get(models.Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    updates = payload.model_dump(exclude_unset=True)
    nullable_fields = {"company_name", "filing_date", "report_period", "fiscal_year", "fiscal_quarter"}
    for field, value in updates.items():
        if field in nullable_fields and value == "":
            value = None
        setattr(document, field, value)
    session.commit()
    session.refresh(document)
    return document_to_read(session, document)


@router.delete("/v1/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str,
    session: DbSession,
    _auth: AuthDep,
) -> Response:
    document = session.get(models.Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    session.delete(document)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/v1/documents/{document_id}/file")
def get_document_file(
    document_id: str,
    session: DbSession,
    settings: SettingsDep,
    _auth: AuthDep,
) -> Response:
    document = session.get(models.Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    store = ObjectStore(settings)
    data = store.get_bytes(
        bucket=document.minio_bucket,
        key=document.minio_key,
        version_id=document.minio_version_id,
    )
    filename_parts = [document.ticker, document.form_type]
    if document.filing_date is not None:
        filename_parts.append(document.filing_date.isoformat())
    filename = "-".join(filename_parts) + ".pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/v1/documents/{document_id}/extracted")
def get_document_extracted(
    document_id: str,
    session: DbSession,
    _auth: AuthDep,
) -> DocumentExtracted:
    document = session.get(models.Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    run_id = document.active_ingestion_run_id
    if run_id is None:
        run_id = session.scalar(
            select(models.IngestionRun.id)
            .where(
                models.IngestionRun.document_id == document_id,
                models.IngestionRun.status == "completed",
            )
            .order_by(models.IngestionRun.created_at.desc())
            .limit(1)
        )
    if run_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No parsed pages for this document")

    pages = list(
        session.scalars(
            select(models.ParsedPage)
            .where(models.ParsedPage.ingestion_run_id == run_id)
            .order_by(models.ParsedPage.page_number)
        )
    )
    if not pages:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No parsed pages for this document")

    return DocumentExtracted(
        document_id=document_id,
        ingestion_run_id=run_id,
        pages=[
            ParsedPageRead(
                page_number=page.page_number,
                text=page.text,
                text_char_count=page.text_char_count,
                table_count=page.table_count,
            )
            for page in pages
        ],
    )
