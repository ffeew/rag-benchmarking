"""Tests for the query-trace retention task.

The integration cases run against the testcontainer Postgres so the
``~exists(...)`` subquery and the Citation FK cascade are exercised against
real SQL rather than an ORM-only simulation. The no-commit unit test mirrors
the equivalent sweeper test so the same invariant is enforced for both
maintenance helpers.
"""

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from rag_common.db import models
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_benchmarking.workers import retention


def _make_trace(
    db_session: Session,
    dataset: models.Dataset,
    *,
    created_at: datetime,
    question: str = "q",
) -> models.QueryTrace:
    """Insert a trace with an explicit ``created_at`` so we can target the
    retention cutoff deterministically.

    ``TimestampMixin`` uses ``server_default=now()``, so we have to overwrite
    ``created_at`` after the row is committed to backdate it.
    """
    trace = models.QueryTrace(
        dataset_id=dataset.id,
        user_question=question,
        retrieval_mode="hybrid",
    )
    db_session.add(trace)
    db_session.commit()
    db_session.refresh(trace)
    trace.created_at = created_at
    db_session.commit()
    db_session.refresh(trace)
    return trace


def _make_eval_run(db_session: Session, dataset: models.Dataset) -> models.EvalRun:
    eval_run = models.EvalRun(dataset_id=dataset.id, system_variant="full_agentic")
    db_session.add(eval_run)
    db_session.commit()
    db_session.refresh(eval_run)
    return eval_run


def _make_eval_result(
    db_session: Session,
    eval_run: models.EvalRun,
    trace: models.QueryTrace,
) -> models.EvalResult:
    eval_result = models.EvalResult(
        eval_run_id=eval_run.id,
        retrieval_mode="hybrid",
        trace_id=trace.id,
    )
    db_session.add(eval_result)
    db_session.commit()
    db_session.refresh(eval_result)
    return eval_result


def _now() -> datetime:
    return datetime.now(UTC)


def test_run_trace_retention_deletes_old_orphan_traces(db_session: Session, seed_dataset: models.Dataset) -> None:
    now = _now()
    old_orphan = _make_trace(db_session, seed_dataset, created_at=now - timedelta(days=45), question="old-orphan")

    report = retention.run_trace_retention(db_session, now=now, retention_days=30)
    db_session.commit()

    assert report["deleted"] == 1
    remaining = list(db_session.scalars(select(models.QueryTrace.id)))
    assert old_orphan.id not in remaining


def test_run_trace_retention_preserves_referenced_traces(db_session: Session, seed_dataset: models.Dataset) -> None:
    now = _now()
    referenced = _make_trace(db_session, seed_dataset, created_at=now - timedelta(days=45), question="referenced")
    eval_run = _make_eval_run(db_session, seed_dataset)
    _make_eval_result(db_session, eval_run, referenced)

    report = retention.run_trace_retention(db_session, now=now, retention_days=30)
    db_session.commit()

    assert report["deleted"] == 0
    remaining = list(db_session.scalars(select(models.QueryTrace.id)))
    assert referenced.id in remaining


def test_run_trace_retention_preserves_fresh_traces(db_session: Session, seed_dataset: models.Dataset) -> None:
    now = _now()
    fresh = _make_trace(db_session, seed_dataset, created_at=now - timedelta(days=5), question="fresh")

    report = retention.run_trace_retention(db_session, now=now, retention_days=30)
    db_session.commit()

    assert report["deleted"] == 0
    remaining = list(db_session.scalars(select(models.QueryTrace.id)))
    assert fresh.id in remaining


def test_run_trace_retention_honors_batch_limit(db_session: Session, seed_dataset: models.Dataset) -> None:
    now = _now()
    for index in range(5):
        _make_trace(db_session, seed_dataset, created_at=now - timedelta(days=45), question=f"orphan-{index}")

    first = retention.run_trace_retention(db_session, now=now, retention_days=30, batch_limit=3)
    db_session.commit()
    second = retention.run_trace_retention(db_session, now=now, retention_days=30, batch_limit=3)
    db_session.commit()

    assert first["deleted"] == 3
    assert second["deleted"] == 2
    assert db_session.scalar(select(models.QueryTrace.id)) is None


def test_run_trace_retention_reports_cutoff_iso(db_session: Session, seed_dataset: models.Dataset) -> None:
    fixed_now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)

    report = retention.run_trace_retention(db_session, now=fixed_now, retention_days=30)

    assert report["cutoff_iso"] == (fixed_now - timedelta(days=30)).isoformat()


def test_run_trace_retention_cascades_to_citations(
    db_session: Session, seed_dataset: models.Dataset, seed_document: models.Document
) -> None:
    """Citation rows pointing at a deleted trace must be removed via the FK
    cascade — the retention helper relies on this instead of doing a manual
    cleanup loop. Skipping the cascade would orphan citations and leak the
    very evidence text we're trying to purge."""
    now = _now()
    trace = _make_trace(db_session, seed_dataset, created_at=now - timedelta(days=45), question="cascaded")

    # Build a Chunk so Citation has the FK targets it needs. The Chunk model
    # is the FK target — ParsedPage isn't referenced by Citation, so we only
    # need an IngestionRun + Chunk to satisfy the schema.
    ingestion_run = models.IngestionRun(
        dataset_id=seed_dataset.id,
        document_id=seed_document.id,
        embedding_model="mock-embedding",
        status="completed",
    )
    db_session.add(ingestion_run)
    db_session.commit()
    db_session.refresh(ingestion_run)
    chunk = models.Chunk(
        document_id=seed_document.id,
        ingestion_run_id=ingestion_run.id,
        page_start=1,
        page_end=1,
        text="snippet",
        normalized_text="snippet",
        token_count=1,
        contains_table=False,
    )
    db_session.add(chunk)
    db_session.commit()
    db_session.refresh(chunk)
    citation = models.Citation(
        trace_id=trace.id,
        chunk_id=chunk.id,
        document_id=seed_document.id,
        page_number=1,
        evidence_text="sensitive excerpt",
        citation_label="[1]",
        minio_bucket=seed_document.minio_bucket,
        minio_key=seed_document.minio_key,
    )
    db_session.add(citation)
    db_session.commit()
    citation_id = citation.id

    retention.run_trace_retention(db_session, now=now, retention_days=30)
    db_session.commit()

    remaining = db_session.scalar(select(models.Citation.id).where(models.Citation.id == citation_id))
    assert remaining is None


def test_run_trace_retention_does_not_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run_trace_retention`` must leave commit responsibility to the caller —
    same invariant as ``sweeper.run_sweep``."""

    class _FakeSession:
        def __init__(self) -> None:
            self.commits = 0

        def scalars(self, _statement: object) -> list[object]:
            return []

        def execute(self, _statement: object) -> None:
            return None

        def commit(self) -> None:
            self.commits += 1

    session = _FakeSession()
    report = retention.run_trace_retention(
        cast("Session", session),
        now=_now(),
        retention_days=30,
    )

    assert report["deleted"] == 0
    assert session.commits == 0
