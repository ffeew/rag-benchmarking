"""End-to-end correctness test for the ingestion pipeline.

Exercises the full parse → chunk → embed → store chain by invoking the
Celery task synchronously against the testcontainer Postgres. The parser
is stubbed (so we don't need a real PDF or Mistral key) and the
``ObjectStore`` is no-opped (so we don't need MinIO running), but every
DB write and every vector goes through the real pgvector + HNSW index.

ALLOW_MOCK_PROVIDERS=true (set in conftest) routes embedding requests
through ``deterministic_embedding`` in ``rag_common.providers.openrouter``,
which returns L2-normalised 1024-dim vectors. That's what lets the
similarity query at the end of ``test_full_pipeline_happy_path`` run
against the real HNSW cosine index without an OpenRouter API call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from rag_common.config import Settings
from rag_common.constants import EMBEDDING_VECTOR_DIMENSION
from rag_common.db import models
from rag_common.enums import ChunkerType, ChunkType, IngestionRunStatus, JobStatus, ParserType
from rag_common.providers.openrouter import OpenRouterClient
from rag_common.storage.minio import ObjectStore
from rag_ingestion_worker import tasks
from rag_ingestion_worker.ingestion import pipeline
from rag_ingestion_worker.ingestion.parsing import ParsedDocumentDraft, ParsedPageDraft
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _seed_ingestion_job(session: Session, document: models.Document) -> models.Job:
    job = models.Job(
        job_type="ingestion",
        status=JobStatus.QUEUED,
        progress=0,
        current_step="queued",
        dataset_id=document.dataset_id,
        document_id=document.id,
        metadata_={"force": False},
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _stub_objectstore(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every ``ObjectStore`` IO with an in-memory no-op.

    The pipeline calls get_bytes (read PDF), put_json (OCR + tables), and
    put_text (per-page markdown). None of them are inspected by the rest of
    the pipeline, so a return value of ``None`` / fixed bytes is sufficient.
    """
    monkeypatch.setattr(ObjectStore, "get_bytes", lambda self, **_: b"%PDF-stub")
    monkeypatch.setattr(ObjectStore, "put_json", lambda self, **_: None)
    monkeypatch.setattr(ObjectStore, "put_text", lambda self, **_: None)


def _stub_parse_pdf(monkeypatch: pytest.MonkeyPatch, draft: ParsedDocumentDraft) -> None:
    monkeypatch.setattr(pipeline, "parse_pdf", lambda *_a, **_kw: draft)


def _make_page(
    page_number: int,
    text_content: str,
    *,
    tables: list[dict[str, Any]] | None = None,
    quality_flags: dict[str, Any] | None = None,
) -> ParsedPageDraft:
    return ParsedPageDraft(
        page_number=page_number,
        text=text_content,
        parser=ParserType.MISTRAL_OCR,
        table_count=len(tables) if tables else 0,
        tables=tables or [],
        quality_flags=quality_flags or {},
        raw={"page_no": page_number},
    )


def _make_draft(pages: list[ParsedPageDraft]) -> ParsedDocumentDraft:
    return ParsedDocumentDraft(
        pages=pages,
        raw_ocr={"parser": ParserType.MISTRAL_OCR, "page_count": len(pages)},
        parser=ParserType.MISTRAL_OCR,
        model="mistral-ocr-stub",
    )


_NARRATIVE = (
    "# Item 1. Business\n\n"
    "Apple Inc. designs, manufactures, and markets smartphones, personal computers, "
    "tablets, wearables, and accessories. The Company's fiscal year is the 52- or 53-week "
    "period that ends on the last Saturday of September.\n\n"
    "The Company sells its products and services through its retail stores, online stores, "
    "and direct sales force, as well as through third-party cellular network carriers, "
    "wholesalers, retailers, and resellers.\n"
)

_TABLE_PAGE = (
    "## Segment revenue (in millions)\n\n"
    "| Segment | 2024 | 2023 | 2022 |\n"
    "| --- | ---: | ---: | ---: |\n"
    "| iPhone | 200,583 | 200,583 | 205,489 |\n"
    "| Mac | 29,357 | 29,357 | 40,177 |\n"
    "| iPad | 26,694 | 28,300 | 29,292 |\n"
    "| Wearables, Home and Accessories | 37,005 | 39,845 | 41,241 |\n"
    "| Services | 85,200 | 78,129 | 78,129 |\n"
)

_MIXED_PAGE = (
    "### Risk factors\n\n"
    "Macroeconomic conditions, including inflation, interest rates, supply chain "
    "disruption, and geopolitical events, can materially affect the Company's results.\n\n"
    "| Region | Net sales | YoY % |\n"
    "| --- | ---: | ---: |\n"
    "| Americas | 167,045 | 3% |\n"
    "| Europe | 101,328 | 7% |\n"
)

_NEAR_EMPTY_PAGE = "Page intentionally left mostly blank."


def test_full_pipeline_happy_path(
    db_session: Session,
    seed_document: models.Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PDF → parse → chunk → embed → store, then query embeddings via pgvector."""
    job = _seed_ingestion_job(db_session, seed_document)

    pages = [
        _make_page(1, _NARRATIVE),
        _make_page(2, _TABLE_PAGE),
        _make_page(3, _MIXED_PAGE),
        _make_page(4, _NEAR_EMPTY_PAGE),
    ]
    _stub_parse_pdf(monkeypatch, _make_draft(pages))
    _stub_objectstore(monkeypatch)

    tasks.ingest_document_task.run(document_id=seed_document.id, job_id=job.id, force=False)

    db_session.expire_all()

    runs = db_session.query(models.IngestionRun).filter_by(document_id=seed_document.id).all()
    assert len(runs) == 1
    run = runs[0]
    assert run.status == IngestionRunStatus.COMPLETED
    assert run.counts["pages"] == 4
    assert run.counts["chunks"] >= 1
    assert run.counts["table_chunks"] >= 1
    assert run.error_summary is None

    db_session.refresh(seed_document)
    assert seed_document.active_ingestion_run_id == run.id

    parsed_pages = db_session.query(models.ParsedPage).filter_by(ingestion_run_id=run.id).all()
    assert sorted(p.page_number for p in parsed_pages) == [1, 2, 3, 4]

    chunks = db_session.query(models.Chunk).filter_by(ingestion_run_id=run.id).all()
    assert chunks, "happy path must produce at least one chunk"
    for chunk in chunks:
        assert chunk.text.strip(), "no chunk should be persisted with empty text"
        assert chunk.page_start <= chunk.page_end
        assert chunk.token_count > 0
        assert chunk.is_active is True
        assert chunk.metadata_["chunker"] == ChunkerType.CHONKIE
        assert chunk.metadata_["chunk_type"] in {ChunkType.NARRATIVE, ChunkType.TABLE, ChunkType.MIXED}
        # Document-level fields are read from Document via FK at retrieval/API time;
        # duplicating them into chunk.metadata is pure waste and was dropped in 0004.
        for redundant in ("ticker", "form_type", "filing_date", "report_period", "parser", "source_object_version"):
            assert redundant not in chunk.metadata_, (
                f"chunk.metadata must not duplicate document/run field {redundant!r}"
            )
        assert chunk.embedding_vector is not None, "every chunk in the happy path must be embedded"
        assert chunk.embedding_dimension == EMBEDDING_VECTOR_DIMENSION
        assert len(chunk.embedding_vector) == EMBEDDING_VECTOR_DIMENSION
        assert chunk.embedding_model

    assert any(chunk.contains_table for chunk in chunks), "table page should produce a table-flagged chunk"

    # Round-trip a similarity query against the HNSW cosine index so we know the
    # written vectors are usable end-to-end (right type, right dim, index covers them).
    # pgvector returns the column as numpy float32 — re-cast to Python floats so
    # ``str([...])`` doesn't render ``np.float32(...)`` wrappers that pgvector's
    # text parser rejects.
    probe_chunk = chunks[0]
    probe = "[" + ",".join(repr(float(v)) for v in probe_chunk.embedding_vector) + "]"
    rows = db_session.execute(
        text(
            "SELECT id FROM chunks WHERE embedding_vector IS NOT NULL "
            "ORDER BY embedding_vector <=> CAST(:probe AS vector) LIMIT 3"
        ),
        {"probe": probe},
    ).all()
    assert rows, "pgvector similarity query must return rows for committed embeddings"
    assert rows[0][0] == probe_chunk.id, "self-similarity must rank the source chunk first"

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.progress == 100


def test_oversized_table_is_recovered(
    db_session: Session,
    seed_document: models.Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single table row wider than ``chunk_max_tokens`` must be recursively split
    instead of being persisted as one chunk that the embedding API would reject.
    """
    job = _seed_ingestion_job(db_session, seed_document)

    # Settings tight enough that the wide rows below force the oversized branch.
    # Settings() picks API_BEARER_TOKEN / ALLOW_MOCK_PROVIDERS up from conftest env.
    custom_settings = Settings(chunk_target_tokens=120, chunk_max_tokens=120, chunk_overlap_tokens=0)
    monkeypatch.setattr(pipeline, "get_settings", lambda: custom_settings)

    # Each row is ~200+ tokens by itself — wider than chunk_max_tokens=120 — so
    # TableChunker can't bring any single piece under the budget.
    wide_cell = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu " * 4
    header = "| C1 | C2 | C3 |"
    sep = "| --- | --- | --- |"
    wide_row = f"| {wide_cell} | {wide_cell} | {wide_cell} |"
    table = "\n".join([header, sep, wide_row, wide_row, wide_row])

    _stub_parse_pdf(monkeypatch, _make_draft([_make_page(1, table)]))
    _stub_objectstore(monkeypatch)

    tasks.ingest_document_task.run(document_id=seed_document.id, job_id=job.id, force=False)

    db_session.expire_all()
    run = db_session.query(models.IngestionRun).filter_by(document_id=seed_document.id).one()
    assert run.status == IngestionRunStatus.COMPLETED

    chunks = db_session.query(models.Chunk).filter_by(ingestion_run_id=run.id).all()
    assert chunks, "oversized table case must still produce chunks (via narrative fallback)"
    assert all(chunk.token_count <= custom_settings.chunk_max_tokens for chunk in chunks), (
        "no chunk should exceed chunk_max_tokens after oversized-recovery"
    )
    assert any(chunk.metadata_.get("oversized_recovered") is True for chunk in chunks), (
        "at least one chunk must carry the oversized_recovered marker"
    )
    # The recovered pieces must still be tagged as table content — losing that
    # tag would let table-only retrieval filters drop them silently.
    recovered = [chunk for chunk in chunks if chunk.metadata_.get("oversized_recovered")]
    assert all(chunk.contains_table for chunk in recovered)


def test_reingest_without_force_reuses_run(
    db_session: Session,
    seed_document: models.Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second ingestion with the same parser_config + chunking_config + embedding_model
    and ``force=False`` must reuse the existing completed run, not re-do the work.
    """
    job_a = _seed_ingestion_job(db_session, seed_document)
    pages = [_make_page(1, _NARRATIVE)]
    _stub_parse_pdf(monkeypatch, _make_draft(pages))
    _stub_objectstore(monkeypatch)

    tasks.ingest_document_task.run(document_id=seed_document.id, job_id=job_a.id, force=False)

    db_session.expire_all()
    first_run = db_session.query(models.IngestionRun).filter_by(document_id=seed_document.id).one()
    first_chunk_count = db_session.query(models.Chunk).filter_by(ingestion_run_id=first_run.id).count()

    job_b = _seed_ingestion_job(db_session, seed_document)
    tasks.ingest_document_task.run(document_id=seed_document.id, job_id=job_b.id, force=False)

    db_session.expire_all()
    runs = db_session.query(models.IngestionRun).filter_by(document_id=seed_document.id).all()
    assert len(runs) == 1, "force=False with matching config must not create a second run row"
    assert runs[0].id == first_run.id

    second_chunk_count = db_session.query(models.Chunk).filter_by(ingestion_run_id=first_run.id).count()
    assert second_chunk_count == first_chunk_count, "chunks must not grow on a reused run"

    db_session.refresh(job_b)
    assert job_b.status == JobStatus.SKIPPED


def test_reingest_with_force_creates_new_run(
    db_session: Session,
    seed_document: models.Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``force=True`` must always create a fresh IngestionRun row and point the
    document's ``active_ingestion_run_id`` at it.
    """
    job_a = _seed_ingestion_job(db_session, seed_document)
    pages = [_make_page(1, _NARRATIVE)]
    _stub_parse_pdf(monkeypatch, _make_draft(pages))
    _stub_objectstore(monkeypatch)

    tasks.ingest_document_task.run(document_id=seed_document.id, job_id=job_a.id, force=False)
    db_session.expire_all()
    first_run = db_session.query(models.IngestionRun).filter_by(document_id=seed_document.id).one()

    job_b = _seed_ingestion_job(db_session, seed_document)
    tasks.ingest_document_task.run(document_id=seed_document.id, job_id=job_b.id, force=True)

    db_session.expire_all()
    runs = (
        db_session.query(models.IngestionRun)
        .filter_by(document_id=seed_document.id)
        .order_by(models.IngestionRun.created_at)
        .all()
    )
    assert len(runs) == 2, "force=True must create a new run row even with matching config"
    second_run = runs[1]
    assert second_run.id != first_run.id
    assert second_run.status == IngestionRunStatus.COMPLETED

    db_session.refresh(seed_document)
    assert seed_document.active_ingestion_run_id == second_run.id

    new_chunks = db_session.query(models.Chunk).filter_by(ingestion_run_id=second_run.id).all()
    assert new_chunks, "force=True must regenerate chunks under the new run"
    for chunk in new_chunks:
        assert chunk.metadata_["chunker"] == ChunkerType.CHONKIE


def test_embedding_dimension_mismatch_rejected_at_settings_load() -> None:
    """``Settings(embedding_dimension=N)`` for N != EMBEDDING_VECTOR_DIMENSION must
    raise at load time so misconfiguration cannot reach the pgvector INSERT.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="EMBEDDING_VECTOR_DIMENSION"):
        Settings(embedding_dimension=EMBEDDING_VECTOR_DIMENSION + 1)


def test_partial_state_survives_mid_embed_failure(
    db_session: Session,
    seed_document: models.Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-batch commits must make the first batch's embeddings durable even
    when a later batch fails. Without that, transient API failures throw away
    every embedding the worker just paid for.
    """
    job = _seed_ingestion_job(db_session, seed_document)

    # Force one-chunk-per-page so 50 pages produce ~50 chunks, guaranteeing at
    # least 2 embedding batches of 32 each. The default target=1000 packs the
    # pages together into one chunk apiece's worth of tokens.
    custom_settings = Settings(chunk_target_tokens=150, chunk_max_tokens=300, chunk_overlap_tokens=0)
    monkeypatch.setattr(pipeline, "get_settings", lambda: custom_settings)

    pages = [_make_page(i, f"Page {i} content: " + _NARRATIVE) for i in range(1, 51)]
    _stub_parse_pdf(monkeypatch, _make_draft(pages))
    _stub_objectstore(monkeypatch)

    # Make the second call to ``OpenRouterClient.embeddings`` raise. Replacing the
    # bound method drops the tenacity retry wrapper so the failure propagates
    # immediately instead of waiting through three exponential backoffs.
    original_embeddings = OpenRouterClient.embeddings
    call_count = 0

    def flaky_embeddings(self: OpenRouterClient, texts: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return original_embeddings(self, texts, **kwargs)
        raise RuntimeError("simulated embedding API outage")

    monkeypatch.setattr(OpenRouterClient, "embeddings", flaky_embeddings)

    with pytest.raises(RuntimeError, match="simulated embedding API outage"):
        tasks.ingest_document_task.run(document_id=seed_document.id, job_id=job.id, force=False)

    db_session.expire_all()

    run = db_session.query(models.IngestionRun).filter_by(document_id=seed_document.id).one()
    assert run.status == IngestionRunStatus.FAILED
    assert run.error_summary is not None and "simulated embedding API outage" in run.error_summary

    parsed_pages = db_session.query(models.ParsedPage).filter_by(ingestion_run_id=run.id).count()
    chunks = db_session.query(models.Chunk).filter_by(ingestion_run_id=run.id).all()
    assert parsed_pages == len(pages), "parsed pages must be durable across an embed-stage failure"
    assert chunks, "chunks must be durable across an embed-stage failure"

    embedded = sum(1 for chunk in chunks if chunk.embedding_vector is not None)
    # First batch (32 chunks) committed; second batch (8 chunks) failed before commit.
    assert 0 < embedded < len(chunks), (
        f"expected partial embedding state (some succeeded, some failed); got {embedded}/{len(chunks)}"
    )

    db_session.refresh(seed_document)
    assert seed_document.active_ingestion_run_id is None, "a failed run must not be promoted to active_ingestion_run_id"

    db_session.refresh(job)
    assert job.status == JobStatus.FAILED


def test_force_reingest_gcs_prior_chunks_same_config(
    db_session: Session,
    seed_document: models.Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful reingest with the same config must delete chunks (including
    their embedding_vector column) and parsed pages from prior runs of the same
    document. Cross-config runs are intentionally preserved (tested elsewhere).
    """
    pages = [_make_page(1, _NARRATIVE)]
    _stub_parse_pdf(monkeypatch, _make_draft(pages))
    _stub_objectstore(monkeypatch)

    job_a = _seed_ingestion_job(db_session, seed_document)
    tasks.ingest_document_task.run(document_id=seed_document.id, job_id=job_a.id, force=False)
    db_session.expire_all()
    first_run = db_session.query(models.IngestionRun).filter_by(document_id=seed_document.id).one()
    first_chunk_count = db_session.query(models.Chunk).filter_by(ingestion_run_id=first_run.id).count()
    assert first_chunk_count > 0

    job_b = _seed_ingestion_job(db_session, seed_document)
    tasks.ingest_document_task.run(document_id=seed_document.id, job_id=job_b.id, force=True)
    db_session.expire_all()

    runs = db_session.query(models.IngestionRun).filter_by(document_id=seed_document.id).all()
    assert len(runs) == 2, "IngestionRun audit rows must be preserved (GC only removes heavyweight data)"

    surviving_first = db_session.query(models.Chunk).filter_by(ingestion_run_id=first_run.id).count()
    surviving_first_pages = db_session.query(models.ParsedPage).filter_by(ingestion_run_id=first_run.id).count()
    assert surviving_first == 0, "prior-run chunks must be GC'd when a same-config run completes"
    assert surviving_first_pages == 0, "prior-run parsed_pages must be GC'd as well"

    second_run = next(r for r in runs if r.id != first_run.id)
    assert second_run.counts["gc_prior_runs"]["chunks"] == first_chunk_count
    assert second_run.counts["gc_prior_runs"]["parsed_pages"] == len(pages)


def test_quality_flags_aggregated_into_run_counts(
    db_session: Session,
    seed_document: models.Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Page-level quality flags must surface in ``IngestionRun.counts`` so
    operators don't have to query individual ParsedPage rows to find them.
    """
    job = _seed_ingestion_job(db_session, seed_document)

    pages = [
        _make_page(1, _NARRATIVE),
        _make_page(2, "", quality_flags={"empty_text": True, "low_text_length": True}),
        _make_page(3, _NEAR_EMPTY_PAGE, quality_flags={"low_text_length": True}),
    ]
    _stub_parse_pdf(monkeypatch, _make_draft(pages))
    _stub_objectstore(monkeypatch)

    tasks.ingest_document_task.run(document_id=seed_document.id, job_id=job.id, force=False)

    db_session.expire_all()
    run = db_session.query(models.IngestionRun).filter_by(document_id=seed_document.id).one()
    assert run.status == IngestionRunStatus.COMPLETED
    assert run.counts["pages_with_quality_flags"] == 2
    assert run.counts["quality_flag_counts"] == {"empty_text": 1, "low_text_length": 2}
