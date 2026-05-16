"""End-to-end regression test for the IngestionRun durability fix.

Bug being guarded: when the worker pipeline raised mid-flight, the
worker's main session rolled back and the ``IngestionRun`` row (including
``status="failed"`` / ``error_summary``) vanished — leaving operators
with a ``failed`` Job and no run record to explain why. The fix commits
the run row on a separate transaction in ``get_or_create_ingestion_run``
and marks failures on yet another transaction in the task-level except.

This test exercises the real Celery task synchronously (``.run(...)``)
against the testcontainer Postgres so the assertions cover the actual
SQLAlchemy session boundaries, not a mocked stand-in.
"""

import pytest
from rag_common.db import models
from rag_common.storage.minio import ObjectStore
from rag_ingestion_worker import tasks
from rag_ingestion_worker.ingestion import pipeline
from sqlalchemy.orm import Session


def _seed_ingestion_job(db_session: Session, document: models.Document) -> models.Job:
    job = models.Job(
        job_type="ingestion",
        status="queued",
        progress=0,
        current_step="queued",
        dataset_id=document.dataset_id,
        document_id=document.id,
        metadata_={"force": False},
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def test_failed_pipeline_persists_ingestion_run_row(
    db_session: Session,
    seed_document: models.Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _seed_ingestion_job(db_session, seed_document)

    monkeypatch.setattr(
        ObjectStore,
        "get_bytes",
        lambda self, *, bucket, key, version_id=None: b"%PDF-fake-bytes",
    )

    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(pipeline, "parse_pdf", boom)

    with pytest.raises(RuntimeError, match="parser exploded"):
        tasks.ingest_document_task.run(document_id=seed_document.id, job_id=job.id, force=False)

    # The test session's identity map is stale — task ran on its own session.
    db_session.expire_all()

    runs = list(
        db_session.query(models.IngestionRun).filter(
            models.IngestionRun.document_id == seed_document.id,
        )
    )
    assert len(runs) == 1, "exactly one IngestionRun row should survive the failure"
    failed = runs[0]
    assert failed.status == "failed"
    assert failed.error_summary is not None
    assert "parser exploded" in failed.error_summary
    assert failed.job_id == job.id

    # Atomicity: the failed run must not leave behind partial parsed pages
    # or chunks — those belong to the rolled-back worker session.
    parsed_pages = db_session.query(models.ParsedPage).filter(models.ParsedPage.ingestion_run_id == failed.id).count()
    chunks = db_session.query(models.Chunk).filter(models.Chunk.ingestion_run_id == failed.id).count()
    assert parsed_pages == 0
    assert chunks == 0

    # And the Job row was independently marked failed (via record_job_failure
    # on yet another transaction).
    db_session.refresh(job)
    assert job.status == "failed"
    assert job.error is not None and "parser exploded" in job.error


def test_failed_pipeline_before_run_creation_still_marks_job_failed(
    db_session: Session,
    seed_document: models.Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the pipeline raises before ``get_or_create_ingestion_run`` is called
    (e.g. document not found), no IngestionRun row is created — and the
    task-level except passes ``run_id=None`` to the helper, which is a no-op.
    The Job must still surface the failure."""
    job = _seed_ingestion_job(db_session, seed_document)

    # Force run_document_ingestion to raise before any run row is created.
    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("pre-run failure")

    monkeypatch.setattr(tasks, "run_document_ingestion", boom)

    with pytest.raises(RuntimeError, match="pre-run failure"):
        tasks.ingest_document_task.run(document_id=seed_document.id, job_id=job.id, force=False)

    db_session.expire_all()
    runs = db_session.query(models.IngestionRun).filter_by(document_id=seed_document.id).count()
    assert runs == 0

    db_session.refresh(job)
    assert job.status == "failed"
    assert job.error is not None and "pre-run failure" in job.error


def test_successful_get_or_create_run_commits_row_eagerly(
    db_session: Session,
    seed_document: models.Document,
) -> None:
    """The bootstrap-commit refactor must make the IngestionRun row visible
    to other sessions immediately, not only after the main pipeline session
    commits. This test calls ``get_or_create_ingestion_run`` on a throwaway
    session, then verifies the row is visible on a *different* session
    without that session having committed."""
    from rag_common.config import get_settings
    from rag_common.db.session import get_sessionmaker

    maker = get_sessionmaker()
    with maker() as worker_session:
        document = worker_session.get(models.Document, seed_document.id)
        assert document is not None
        run, created = pipeline.get_or_create_ingestion_run(
            worker_session,
            document=document,
            job=None,
            force=False,
            settings=get_settings(),
        )
        assert created is True
        run_id = run.id
        # NOTE: we deliberately do NOT call worker_session.commit() here.
        # The whole point of the fix is that the row is durable without it.

    # New independent session — should see the row.
    with maker() as observer:
        observed = observer.get(models.IngestionRun, run_id)
        assert observed is not None
        assert observed.status == "queued"
        assert observed.document_id == seed_document.id
