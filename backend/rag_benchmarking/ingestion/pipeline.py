import time
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from rag_benchmarking.core.config import Settings, get_settings
from rag_benchmarking.db import models
from rag_benchmarking.ingestion.chunking import chunk_pages, normalize_text
from rag_benchmarking.ingestion.parsing import parse_pdf
from rag_benchmarking.providers.openrouter import OpenRouterClient
from rag_benchmarking.storage.minio import ObjectStore
from rag_benchmarking.workers.job_state import commit_job_progress

logger = structlog.get_logger(__name__)


def artifact_prefix(dataset_id: str, document_id: str, run_id: str) -> str:
    return f"artifacts/{dataset_id}/{document_id}/{run_id}"


def parser_config(settings: Settings) -> dict[str, Any]:
    return {
        "primary": "mistral-ocr",
        "fallback": "pypdf-local",
        "ocr_model": settings.mistral_ocr_model,
        "allow_mock_providers": settings.allow_mock_providers,
    }


def chunking_config(settings: Settings) -> dict[str, Any]:
    return {
        "chunker": "chonkie",
        "target_tokens": settings.chunk_target_tokens,
        "max_tokens": settings.chunk_max_tokens,
        "overlap_tokens": settings.chunk_overlap_tokens,
        "table_max_rows": settings.table_max_rows,
    }


def get_or_create_ingestion_run(
    session: Session,
    *,
    document: models.Document,
    job: models.Job | None,
    force: bool,
    settings: Settings,
) -> tuple[models.IngestionRun, bool]:
    config = parser_config(settings)
    chunks = chunking_config(settings)
    embedding_model = settings.openrouter_embedding_model or "mock-embedding"
    if not force:
        existing = session.scalar(
            select(models.IngestionRun)
            .where(
                models.IngestionRun.document_id == document.id,
                models.IngestionRun.parser_config == config,
                models.IngestionRun.chunking_config == chunks,
                models.IngestionRun.embedding_model == embedding_model,
                models.IngestionRun.status == "completed",
            )
            .order_by(models.IngestionRun.created_at.desc())
        )
        if existing:
            return existing, False
    run = models.IngestionRun(
        dataset_id=document.dataset_id,
        document_id=document.id,
        job_id=job.id if job else None,
        parser_config=config,
        chunking_config=chunks,
        embedding_model=embedding_model,
        status="queued",
    )
    session.add(run)
    session.flush()
    return run, True


def mark_job(
    session: Session,  # noqa: ARG001 - kept for API stability; writes go via commit_job_progress
    job: models.Job | None,
    *,
    status: str,
    progress: int,
    step: str | None,
    error: str | None = None,
) -> None:
    """Durably advance a job's status/progress/heartbeat.

    Updates are committed on a *separate* transaction so the heartbeat is
    visible to the API/UI even while the main pipeline session is still
    holding uncommitted ingestion data, and so a worker crash later in the
    pipeline does not roll back every progress checkpoint along the way.
    """
    if job is None:
        return
    commit_job_progress(
        job.id,
        status=status,
        progress=progress,
        current_step=step,
        error=error,
    )


def run_document_ingestion(
    session: Session,
    *,
    document_id: str,
    job_id: str | None = None,
    force: bool = False,
    settings: Settings | None = None,
) -> models.IngestionRun:
    resolved = settings or get_settings()
    log = logger.bind(document_id=document_id, job_id=job_id)
    pipeline_start = time.perf_counter()
    log.info(
        "pipeline_enter",
        force=force,
        allow_mock_providers=resolved.allow_mock_providers,
    )
    document = session.get(models.Document, document_id)
    if document is None:
        log.error("pipeline_document_not_found")
        raise ValueError(f"Document {document_id} was not found")
    job = session.get(models.Job, job_id) if job_id else None

    run, should_ingest = get_or_create_ingestion_run(
        session,
        document=document,
        job=job,
        force=force,
        settings=resolved,
    )
    log = log.bind(run_id=run.id, dataset_id=document.dataset_id)
    log.info("pipeline_run_resolved", should_ingest=should_ingest)
    if not should_ingest:
        mark_job(session, job, status="skipped", progress=100, step="already indexed")
        log.info("pipeline_skipped_already_indexed")
        return run

    store = ObjectStore(resolved)
    provider = OpenRouterClient(resolved)
    try:
        mark_job(session, job, status="running", progress=5, step="reading raw PDF")
        run.status = "running"
        log.info(
            "pipeline_stage_minio_get_start",
            bucket=document.minio_bucket,
            key=document.minio_key,
            version_id=document.minio_version_id,
        )
        stage_started = time.perf_counter()
        pdf_bytes = store.get_bytes(
            bucket=document.minio_bucket,
            key=document.minio_key,
            version_id=document.minio_version_id,
        )
        log.info(
            "pipeline_stage_minio_get_done",
            bytes=len(pdf_bytes),
            elapsed_seconds=round(time.perf_counter() - stage_started, 3),
        )

        mark_job(session, job, status="running", progress=20, step="parsing document")
        log.info("pipeline_stage_parse_start")
        stage_started = time.perf_counter()
        parsed = parse_pdf(pdf_bytes, resolved)
        log.info(
            "pipeline_stage_parse_done",
            parser=parsed.parser,
            model=parsed.model,
            pages=len(parsed.pages),
            elapsed_seconds=round(time.perf_counter() - stage_started, 3),
        )
        prefix = artifact_prefix(document.dataset_id, document.id, run.id)
        log.info("pipeline_stage_artifacts_upload_start", page_count=len(parsed.pages))
        stage_started = time.perf_counter()
        store.put_json(key=f"{prefix}/ocr.json", payload=parsed.raw_ocr)
        session.execute(delete(models.ParsedPage).where(models.ParsedPage.ingestion_run_id == run.id))
        for page in parsed.pages:
            artifact_key = f"{prefix}/pages/{page.page_number}.md"
            store.put_text(key=artifact_key, text=page.text)
            if page.table_count:
                store.put_json(key=f"{prefix}/tables/{page.page_number}.json", payload=page.raw.get("tables", []))
            session.add(
                models.ParsedPage(
                    ingestion_run_id=run.id,
                    document_id=document.id,
                    page_number=page.page_number,
                    parser=page.parser,
                    artifact_key=artifact_key,
                    text=page.text,
                    text_char_count=len(page.text),
                    table_count=page.table_count,
                    quality_flags=page.quality_flags,
                    source_minio_key=document.minio_key,
                    source_minio_version_id=document.minio_version_id,
                )
            )
        session.flush()
        log.info(
            "pipeline_stage_artifacts_upload_done",
            elapsed_seconds=round(time.perf_counter() - stage_started, 3),
        )

        mark_job(session, job, status="running", progress=50, step="chunking parsed pages")
        log.info("pipeline_stage_chunk_start")
        stage_started = time.perf_counter()
        pages = list(
            session.scalars(
                select(models.ParsedPage)
                .where(models.ParsedPage.ingestion_run_id == run.id)
                .order_by(models.ParsedPage.page_number)
            )
        )
        chunk_ids_for_run = select(models.Chunk.id).where(models.Chunk.ingestion_run_id == run.id)
        session.execute(delete(models.Embedding).where(models.Embedding.chunk_id.in_(chunk_ids_for_run)))
        session.execute(delete(models.Chunk).where(models.Chunk.ingestion_run_id == run.id))
        chunks = chunk_pages(pages, resolved)
        db_chunks: list[models.Chunk] = []
        for draft in chunks:
            metadata = {
                **draft.metadata,
                "ticker": document.ticker,
                "form_type": document.form_type,
                "filing_date": document.filing_date.isoformat() if document.filing_date else None,
                "report_period": document.report_period.isoformat() if document.report_period else None,
                "parser": parsed.parser,
                "source_object_version": document.minio_version_id,
            }
            chunk = models.Chunk(
                ingestion_run_id=run.id,
                document_id=document.id,
                page_start=draft.page_start,
                page_end=draft.page_end,
                text=draft.text,
                normalized_text=normalize_text(draft.text),
                contains_table=draft.contains_table,
                token_count=draft.token_count,
                metadata_=metadata,
                source_offsets=draft.source_offsets,
                is_active=True,
            )
            session.add(chunk)
            db_chunks.append(chunk)
        session.flush()
        log.info(
            "pipeline_stage_chunk_done",
            chunk_count=len(db_chunks),
            elapsed_seconds=round(time.perf_counter() - stage_started, 3),
        )

        mark_job(session, job, status="running", progress=75, step="embedding chunks")
        batch_size = 32
        embedding_model = resolved.openrouter_embedding_model or "mock-embedding"
        log.info(
            "pipeline_stage_embed_start",
            embedding_model=embedding_model,
            total_chunks=len(db_chunks),
            batch_size=batch_size,
        )
        stage_started = time.perf_counter()
        for offset in range(0, len(db_chunks), batch_size):
            batch = db_chunks[offset : offset + batch_size]
            batch_started = time.perf_counter()
            log.info(
                "pipeline_stage_embed_batch_start",
                batch_index=offset // batch_size,
                batch_size=len(batch),
                offset=offset,
            )
            result = provider.embeddings([chunk.text for chunk in batch], model=embedding_model)
            for chunk, vector in zip(batch, result.vectors, strict=True):
                session.add(
                    models.Embedding(
                        chunk_id=chunk.id,
                        provider=result.metadata.provider,
                        model=result.metadata.model or embedding_model,
                        dimension=len(vector),
                        vector=vector,
                    )
                )
            log.info(
                "pipeline_stage_embed_batch_done",
                batch_index=offset // batch_size,
                batch_size=len(batch),
                provider=result.metadata.provider,
                elapsed_seconds=round(time.perf_counter() - batch_started, 3),
            )
        log.info(
            "pipeline_stage_embed_done",
            elapsed_seconds=round(time.perf_counter() - stage_started, 3),
        )
        run.status = "completed"
        run.timings = {"total_seconds": round(time.perf_counter() - pipeline_start, 3)}
        run.counts = {
            "pages": len(pages),
            "chunks": len(db_chunks),
            "table_chunks": sum(1 for chunk in db_chunks if chunk.contains_table),
        }
        document.active_ingestion_run_id = run.id
        mark_job(session, job, status="completed", progress=100, step="completed")
        session.flush()
        log.info(
            "pipeline_completed",
            pages=len(pages),
            chunks=len(db_chunks),
            elapsed_seconds=round(time.perf_counter() - pipeline_start, 3),
        )
        return run
    except Exception as exc:
        run.status = "failed"
        run.error_summary = str(exc)
        mark_job(session, job, status="failed", progress=100, step="failed", error=str(exc))
        session.flush()
        log.exception(
            "pipeline_failed",
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
            elapsed_seconds=round(time.perf_counter() - pipeline_start, 3),
        )
        raise
