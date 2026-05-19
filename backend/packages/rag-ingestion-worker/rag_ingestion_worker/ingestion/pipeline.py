import time
from typing import Any, cast

import structlog
from rag_common.config import Settings, get_settings
from rag_common.db import models
from rag_common.db.session import get_sessionmaker
from rag_common.enums import ChunkerType, IngestionRunStatus, JobStatus, ParserType
from rag_common.ingestion_run_state import record_ingestion_run_failure
from rag_common.job_state import commit_job_progress
from rag_common.providers.openrouter import OpenRouterClient
from rag_common.storage.minio import ObjectStore
from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.orm import Session

from rag_ingestion_worker.ingestion.chunking import chunk_pages, normalize_text
from rag_ingestion_worker.ingestion.parsing import parse_pdf

logger = structlog.get_logger(__name__)


def artifact_prefix(dataset_id: str, document_id: str, run_id: str) -> str:
    return f"artifacts/{dataset_id}/{document_id}/{run_id}"


def parser_config(settings: Settings) -> dict[str, Any]:
    # Mistral OCR is bypassed when mocks are on, or when MISTRAL_API_KEY is
    # unset (operator opted out of hosted OCR). Reflect that in the dedup key
    # so a docling-only run does NOT collide with a real OCR run and silently
    # re-use its chunks.
    mistral_available = bool(settings.mistral_api_key) and not settings.allow_mock_providers
    primary = ParserType.MISTRAL_OCR if mistral_available else ParserType.DOCLING
    return {
        "primary": primary,
        "fallback": ParserType.DOCLING,
        "last_resort": ParserType.PYPDF_LOCAL,
        "ocr_model": settings.mistral_ocr_model,
        "ocr_transport": "base64_data_uri",
        "table_format": "inline_markdown",
        "include_image_base64": False,
        "allow_mock_providers": settings.allow_mock_providers,
        "mistral_ocr_available": mistral_available,
    }


def chunking_config(settings: Settings) -> dict[str, Any]:
    # Surface the tokenizer the recursive chunker actually loaded so a character-mode
    # fallback (offline boot, tiktoken cache miss) does NOT collide with a real
    # cl100k_base run in the IngestionRun dedup key.
    from rag_ingestion_worker.ingestion.chunking import active_tokenizer_mode

    return {
        "chunker": ChunkerType.CHONKIE,
        "target_tokens": settings.chunk_target_tokens,
        "max_tokens": settings.chunk_max_tokens,
        "overlap_tokens": settings.chunk_overlap_tokens,
        "table_max_rows": settings.table_max_rows,
        "tokenizer_mode": active_tokenizer_mode(settings.chunk_target_tokens),
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
                models.IngestionRun.status == IngestionRunStatus.COMPLETED,
            )
            .order_by(models.IngestionRun.created_at.desc())
        )
        if existing:
            return existing, False

    # Bootstrap-commit the new row on a SEPARATE transaction. The caller's
    # session will hold uncommitted ParsedPage/Chunk writes for
    # the rest of the pipeline; committing the run row up-front makes it
    # visible to the API/UI immediately and lets the task-level except
    # mark it failed on yet another transaction if the pipeline raises.
    maker = get_sessionmaker()
    with maker() as bootstrap:
        run = models.IngestionRun(
            dataset_id=document.dataset_id,
            document_id=document.id,
            job_id=job.id if job else None,
            parser_config=config,
            chunking_config=chunks,
            embedding_model=embedding_model,
            status=IngestionRunStatus.QUEUED,
        )
        bootstrap.add(run)
        bootstrap.commit()
        run_id = run.id

    attached = session.get(models.IngestionRun, run_id)
    if attached is None:
        # The bootstrap transaction above committed run_id to the same database
        # the caller session is bound to, so a missing row here indicates a real
        # infrastructure problem (replica routing, transaction isolation higher
        # than read-committed, connection mismatch). Raise instead of asserting
        # so the check survives Python -O.
        raise RuntimeError(
            f"IngestionRun {run_id} was committed in a bootstrap transaction but is "
            "not visible to the worker session. Check that the worker and bootstrap "
            "sessions share the same database / connection pool."
        )
    return attached, True


def gc_prior_runs_same_config(
    session: Session,
    *,
    document_id: str,
    current_run_id: str,
    parser_config_value: dict[str, Any],
    chunking_config_value: dict[str, Any],
    embedding_model: str,
) -> dict[str, int]:
    """Delete heavyweight artifacts (parsed_pages, chunks) from prior
    ``IngestionRun`` rows for ``document_id`` whose config matches the current run.

    Different-config runs are intentionally preserved so cross-config benchmarking
    keeps working — this only collapses duplicates within a single config tuple
    that the dedup query would normally have reused but couldn't (because the
    prior run failed, or the caller passed ``force=True``). The IngestionRun
    rows themselves stay for audit (status, error_summary, timings, counts).

    Citations to deleted chunks cascade-delete via the FK; that is the
    intended behavior because citations carry their own ``evidence_text``
    snapshot for the answer-quality record.
    """
    prior_run_ids = select(models.IngestionRun.id).where(
        models.IngestionRun.document_id == document_id,
        models.IngestionRun.id != current_run_id,
        models.IngestionRun.parser_config == parser_config_value,
        models.IngestionRun.chunking_config == chunking_config_value,
        models.IngestionRun.embedding_model == embedding_model,
    )
    # ``session.execute(delete(...))`` always returns a ``CursorResult`` at
    # runtime, but SQLAlchemy's stub types it as ``Result[Any]`` (which omits
    # ``rowcount``). Cast so mypy can see the DML-specific attribute.
    chunks_result = cast(
        "CursorResult[Any]",
        session.execute(delete(models.Chunk).where(models.Chunk.ingestion_run_id.in_(prior_run_ids))),
    )
    parsed_pages_result = cast(
        "CursorResult[Any]",
        session.execute(delete(models.ParsedPage).where(models.ParsedPage.ingestion_run_id.in_(prior_run_ids))),
    )
    return {
        "chunks": chunks_result.rowcount,
        "parsed_pages": parsed_pages_result.rowcount,
    }


def quality_flag_summary(pages: list[Any]) -> dict[str, int]:
    """Aggregate ``quality_flags`` set across all parsed pages.

    Returns a per-flag count (e.g. ``{"empty_text": 2, "malformed_markdown_table": 1}``)
    so degraded OCR runs leave a fingerprint in ``IngestionRun.counts`` instead of
    being silently absorbed into the chunk pipeline.
    """
    summary: dict[str, int] = {}
    for page in pages:
        for flag, value in page.quality_flags.items():
            if value:
                summary[flag] = summary.get(flag, 0) + 1
    return summary


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
    log.debug(
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
    log.debug("pipeline_run_resolved", should_ingest=should_ingest)
    if not should_ingest:
        mark_job(session, job, status=JobStatus.SKIPPED, progress=100, step="already indexed")
        log.info("pipeline_skipped_already_indexed")
        return run

    store = ObjectStore(resolved)
    provider = OpenRouterClient(resolved)
    resolved_parser_config = parser_config(resolved)
    resolved_chunking_config = chunking_config(resolved)
    resolved_embedding_model = resolved.openrouter_embedding_model or "mock-embedding"
    try:
        mark_job(session, job, status=JobStatus.RUNNING, progress=5, step="reading raw PDF")
        run.status = IngestionRunStatus.RUNNING
        # Surface RUNNING immediately. Without this commit the row remains at its
        # bootstrap QUEUED value for the entire pipeline, so an operator watching
        # ``IngestionRun.status`` cannot distinguish a worker that is hard at work
        # from one that died after picking up the task.
        session.commit()
        log.debug(
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
        log.debug(
            "pipeline_stage_minio_get_done",
            bytes=len(pdf_bytes),
            elapsed_seconds=round(time.perf_counter() - stage_started, 3),
        )

        mark_job(session, job, status=JobStatus.RUNNING, progress=20, step="parsing document")
        log.debug("pipeline_stage_parse_start")
        stage_started = time.perf_counter()
        parsed = parse_pdf(pdf_bytes, resolved)
        page_quality_summary = quality_flag_summary(parsed.pages)
        if page_quality_summary:
            # Per-page quality flags previously went into ``ParsedPage.quality_flags``
            # and were never read again. Aggregate and log them here so a run with
            # mostly-empty pages or malformed tables is visible at the warning level.
            log.warning(
                "pipeline_quality_flags_detected",
                flag_counts=page_quality_summary,
                affected_pages=sum(1 for page in parsed.pages if page.quality_flags),
                total_pages=len(parsed.pages),
            )
        log.debug(
            "pipeline_stage_parse_done",
            parser=parsed.parser,
            model=parsed.model,
            pages=len(parsed.pages),
            elapsed_seconds=round(time.perf_counter() - stage_started, 3),
        )
        prefix = artifact_prefix(document.dataset_id, document.id, run.id)
        log.debug("pipeline_stage_artifacts_upload_start", page_count=len(parsed.pages))
        stage_started = time.perf_counter()
        store.put_json(key=f"{prefix}/ocr.json", payload=parsed.raw_ocr)
        session.execute(delete(models.ParsedPage).where(models.ParsedPage.ingestion_run_id == run.id))
        for page in parsed.pages:
            artifact_key = f"{prefix}/pages/{page.page_number}.md"
            store.put_text(key=artifact_key, text=page.text)
            if page.table_count:
                store.put_json(key=f"{prefix}/tables/{page.page_number}.json", payload=page.tables)
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
        # Make parsed pages durable before chunking. A chunker or embedding failure
        # after this point no longer discards the OCR work; the parsed-page rows
        # belong to this (failed) run and are GC'd by ``gc_prior_runs_same_config``
        # once a later attempt succeeds with the same config.
        session.commit()
        log.debug(
            "pipeline_stage_artifacts_upload_done",
            elapsed_seconds=round(time.perf_counter() - stage_started, 3),
        )

        mark_job(session, job, status=JobStatus.RUNNING, progress=50, step="chunking parsed pages")
        log.debug("pipeline_stage_chunk_start")
        stage_started = time.perf_counter()
        pages = list(
            session.scalars(
                select(models.ParsedPage)
                .where(models.ParsedPage.ingestion_run_id == run.id)
                .order_by(models.ParsedPage.page_number)
            )
        )
        session.execute(delete(models.Chunk).where(models.Chunk.ingestion_run_id == run.id))
        chunks = chunk_pages(pages, resolved)
        db_chunks: list[models.Chunk] = []
        for draft in chunks:
            chunk = models.Chunk(
                ingestion_run_id=run.id,
                document_id=document.id,
                page_start=draft.page_start,
                page_end=draft.page_end,
                text=draft.text,
                normalized_text=normalize_text(draft.text),
                contains_table=draft.contains_table,
                token_count=draft.token_count,
                metadata_=draft.metadata,
                source_offsets=draft.source_offsets,
                is_active=True,
            )
            session.add(chunk)
            db_chunks.append(chunk)
        session.flush()
        # Make chunks durable before the (potentially long, network-bound)
        # embedding stage. If a batch later fails, the chunk rows survive under
        # this run for analysis; ``gc_prior_runs_same_config`` cleans them up
        # when a subsequent attempt of the same config succeeds.
        session.commit()
        log.debug(
            "pipeline_stage_chunk_done",
            chunk_count=len(db_chunks),
            elapsed_seconds=round(time.perf_counter() - stage_started, 3),
        )

        mark_job(session, job, status=JobStatus.RUNNING, progress=75, step="embedding chunks")
        batch_size = 32
        embedding_model = resolved.openrouter_embedding_model or "mock-embedding"
        log.debug(
            "pipeline_stage_embed_start",
            embedding_model=embedding_model,
            total_chunks=len(db_chunks),
            batch_size=batch_size,
        )
        stage_started = time.perf_counter()
        total_batches = max(1, (len(db_chunks) + batch_size - 1) // batch_size)
        for offset in range(0, len(db_chunks), batch_size):
            batch = db_chunks[offset : offset + batch_size]
            batch_started = time.perf_counter()
            batch_index = offset // batch_size
            log.debug(
                "pipeline_stage_embed_batch_start",
                batch_index=batch_index,
                batch_size=len(batch),
                offset=offset,
            )
            result = provider.embeddings(
                [chunk.text for chunk in batch],
                model=embedding_model,
                dimensions=resolved.embedding_dimension,
            )
            resolved_model = result.metadata.model or embedding_model
            # SQLAlchemy 2.x "ORM Bulk UPDATE by Primary Key": passing a list of
            # dicts that include the PK column triggers a single executemany
            # round-trip with implicit ``WHERE id = :id``. One DB round-trip per
            # 32-chunk batch instead of 32 INSERTs.
            session.execute(
                update(models.Chunk),
                [
                    {
                        "id": chunk.id,
                        "embedding_vector": vector,
                        "embedding_provider": result.metadata.provider,
                        "embedding_model": resolved_model,
                        "embedding_dimension": len(vector),
                    }
                    for chunk, vector in zip(batch, result.vectors, strict=True)
                ],
            )
            # Commit each batch so a later batch's failure doesn't undo embedding
            # cost we've already paid. Combined with ``gc_prior_runs_same_config``
            # on the next successful retry, this turns "any embed failure throws
            # away the whole run" into "any embed failure costs at most one batch
            # of recomputation". Unembedded chunks keep ``embedding_vector IS NULL``
            # and are filtered out of semantic retrieval.
            session.commit()
            # 75–95% of the progress bar covers embedding so a hung batch is
            # visible in the UI; reserve the last 5 points for the final GC + commit.
            progress_pct = 75 + int(20 * (batch_index + 1) / total_batches)
            mark_job(
                session,
                job,
                status=JobStatus.RUNNING,
                progress=progress_pct,
                step=f"embedding batch {batch_index + 1}/{total_batches}",
            )
            log.debug(
                "pipeline_stage_embed_batch_done",
                batch_index=batch_index,
                batch_size=len(batch),
                provider=result.metadata.provider,
                elapsed_seconds=round(time.perf_counter() - batch_started, 3),
            )
        log.debug(
            "pipeline_stage_embed_done",
            elapsed_seconds=round(time.perf_counter() - stage_started, 3),
        )
        run.status = IngestionRunStatus.COMPLETED
        run.timings = {"total_seconds": round(time.perf_counter() - pipeline_start, 3)}
        run.counts = {
            "pages": len(pages),
            "chunks": len(db_chunks),
            "table_chunks": sum(1 for chunk in db_chunks if chunk.contains_table),
            "pages_with_quality_flags": sum(1 for page in parsed.pages if page.quality_flags),
            "quality_flag_counts": page_quality_summary,
        }
        document.active_ingestion_run_id = run.id
        # GC chunks/embeddings/parsed_pages from earlier same-config runs of this
        # document (whether they completed earlier or failed mid-way thanks to the
        # per-stage commits above). Cross-config runs survive so cross-config
        # benchmarking remains intact; the dedup query already keys on this same
        # tuple so this is just "collapse duplicates within a config".
        gc_counts = gc_prior_runs_same_config(
            session,
            document_id=document.id,
            current_run_id=run.id,
            parser_config_value=resolved_parser_config,
            chunking_config_value=resolved_chunking_config,
            embedding_model=resolved_embedding_model,
        )
        run.counts["gc_prior_runs"] = gc_counts
        mark_job(session, job, status=JobStatus.COMPLETED, progress=100, step="completed")
        session.flush()
        log.info(
            "pipeline_completed",
            pages=len(pages),
            chunks=len(db_chunks),
            quality_flags=page_quality_summary,
            gc_counts=gc_counts,
            elapsed_seconds=round(time.perf_counter() - pipeline_start, 3),
        )
        return run
    except Exception as exc:
        # Discard uncommitted state on the worker session before we touch external
        # state. Per-stage commits above mean previously committed parsed_pages,
        # chunks, and embedded batches are durable under this (now-failed) run —
        # ``gc_prior_runs_same_config`` collapses them when a later attempt with
        # the same config succeeds. The rollback here only covers what hadn't
        # been committed yet (typically the current batch of embeddings).
        session.rollback()
        # Mark the run and job failed via separate transactions. Both helpers
        # refuse to clobber terminal statuses, so a follow-up call from the
        # task-level except is a safe no-op.
        record_ingestion_run_failure(run.id, str(exc))
        mark_job(session, job, status=JobStatus.FAILED, progress=100, step="failed", error=str(exc))
        log.exception(
            "pipeline_failed",
            exception_type=exc.__class__.__name__,
            exception_message=str(exc),
            elapsed_seconds=round(time.perf_counter() - pipeline_start, 3),
        )
        raise
