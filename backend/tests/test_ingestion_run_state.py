"""Unit tests for ``rag_common.ingestion_run_state``.

Mirror the structure of the existing ``job_state`` coverage (which lives
inside ``test_fault_tolerance.py`` as ``test_commit_job_progress_*``) but
exercise the new IngestionRun helper directly. Uses the real testcontainer
DB so ``FOR KEY SHARE`` row locks and JSONB merge behavior are exercised
end-to-end.
"""

from rag_common.db import models
from rag_common.ingestion_run_state import record_ingestion_run_failure
from sqlalchemy.orm import Session


def _insert_run(db_session: Session, document: models.Document, **overrides: object) -> models.IngestionRun:
    fields: dict[str, object] = {
        "dataset_id": document.dataset_id,
        "document_id": document.id,
        "parser_config": {"primary": "mock"},
        "chunking_config": {"chunker": "mock"},
        "embedding_model": "mock-embedding",
        "status": "running",
    }
    fields.update(overrides)
    run = models.IngestionRun(**fields)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def test_failure_marks_existing_run_failed(db_session: Session, seed_document: models.Document) -> None:
    run = _insert_run(db_session, seed_document)

    record_ingestion_run_failure(run.id, "RuntimeError: boom")

    db_session.expire_all()
    refreshed = db_session.get(models.IngestionRun, run.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.error_summary == "RuntimeError: boom"
    assert "failed_at" in refreshed.timings


def test_failure_preserves_completed_status(db_session: Session, seed_document: models.Document) -> None:
    run = _insert_run(db_session, seed_document, status="completed")

    record_ingestion_run_failure(run.id, "stale failure")

    db_session.expire_all()
    refreshed = db_session.get(models.IngestionRun, run.id)
    assert refreshed is not None
    assert refreshed.status == "completed"
    assert refreshed.error_summary is None


def test_failure_preserves_skipped_status(db_session: Session, seed_document: models.Document) -> None:
    run = _insert_run(db_session, seed_document, status="skipped")

    record_ingestion_run_failure(run.id, "should not overwrite")

    db_session.expire_all()
    refreshed = db_session.get(models.IngestionRun, run.id)
    assert refreshed is not None
    assert refreshed.status == "skipped"


def test_failure_missing_run_is_noop() -> None:
    # Unknown id should be silent (logged but not raised).
    record_ingestion_run_failure("does-not-exist", "boom")


def test_failure_none_run_id_is_noop() -> None:
    record_ingestion_run_failure(None, "boom")


def test_failure_truncates_long_error_summary(db_session: Session, seed_document: models.Document) -> None:
    run = _insert_run(db_session, seed_document)
    long_error = "x" * 20_000

    record_ingestion_run_failure(run.id, long_error)

    db_session.expire_all()
    refreshed = db_session.get(models.IngestionRun, run.id)
    assert refreshed is not None
    assert refreshed.error_summary is not None
    assert len(refreshed.error_summary) == 8000
