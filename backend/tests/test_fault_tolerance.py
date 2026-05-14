from datetime import UTC, datetime, timedelta
from types import SimpleNamespace, TracebackType
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from rag_benchmarking.api import serialization
from rag_benchmarking.db import models
from rag_benchmarking.ingestion import queueing
from rag_benchmarking.workers import dispatch, job_state, sweeper, tasks


class _FakeAsyncResult:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _FakeTask:
    """Stand-in for a Celery task that records the kwargs it was sent and
    optionally raises to simulate broker failure."""

    def __init__(self, task_id: str = "fake-task-id", *, should_fail: bool = False) -> None:
        self.task_id = task_id
        self.should_fail = should_fail
        self.calls: list[dict[str, Any]] = []

    def apply_async(self, *, kwargs: dict[str, Any]) -> _FakeAsyncResult:
        self.calls.append(kwargs)
        if self.should_fail:
            raise RuntimeError("broker down")
        return _FakeAsyncResult(self.task_id)


def _make_job(**overrides: Any) -> models.Job:
    defaults: dict[str, Any] = {
        "id": "job-1",
        "job_type": "ingestion",
        "status": "queued",
        "progress": 0,
        "current_step": "queued",
        "celery_task_id": None,
        "dataset_id": "ds-1",
        "document_id": "doc-1",
        "eval_run_id": None,
        "error": None,
        "metadata_": {},
        "retry_count": 0,
        "last_heartbeat_at": None,
        "started_at": None,
        "completed_at": None,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    # Job is a real SQLAlchemy model — use cast to bypass typing since we never
    # persist these in this unit-test file. Construct as a SimpleNamespace so
    # attribute writes don't trigger ORM machinery.
    return cast("models.Job", SimpleNamespace(**defaults))


def _make_document(**overrides: Any) -> models.Document:
    defaults: dict[str, Any] = {
        "id": "doc-1",
        "dataset_id": "ds-1",
        "ticker": "AAPL",
        "company_name": None,
        "form_type": "10-K",
        "filing_date": None,
        "report_period": None,
        "fiscal_year": None,
        "fiscal_quarter": None,
        "checksum": "abc",
        "minio_bucket": "sec-filings",
        "minio_key": "raw/ds-1/AAPL/10-K/abc.pdf",
        "minio_version_id": None,
        "byte_size": 123,
        "active_ingestion_run_id": None,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return cast("models.Document", SimpleNamespace(**defaults))


class _FakeQueueSession:
    def __init__(self) -> None:
        self.added_jobs: list[models.Job] = []
        self.commits = 0

    def add(self, item: object) -> None:
        if not isinstance(item, models.Job):
            return
        if not item.id:
            item.id = f"job-{len(self.added_jobs) + 1}"
        self.added_jobs.append(item)

    def commit(self) -> None:
        self.commits += 1

    def scalar(self, _statement: object) -> None:
        return None


class _FakeWorkerSession:
    def __init__(self) -> None:
        self.committed = False

    def __enter__(self) -> "_FakeWorkerSession":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


def test_dispatch_job_routes_ingestion(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeTask("ing-task")
    monkeypatch.setattr(dispatch, "ingest_document_task", fake)
    job = _make_job(metadata_={"force": True})

    task_id = dispatch.dispatch_job(job)

    assert task_id == "ing-task"
    assert fake.calls == [{"document_id": "doc-1", "job_id": "job-1", "force": True}]


def test_dispatch_job_routes_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeTask("eval-task")
    monkeypatch.setattr(dispatch, "run_evaluation_task", fake)
    job = _make_job(job_type="evaluation", document_id=None, eval_run_id="run-7")

    task_id = dispatch.dispatch_job(job)

    assert task_id == "eval-task"
    assert fake.calls == [{"eval_run_id": "run-7", "job_id": "job-1"}]


def test_dispatch_job_returns_none_on_broker_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeTask(should_fail=True)
    monkeypatch.setattr(dispatch, "ingest_document_task", fake)

    result = dispatch.dispatch_job(_make_job())
    assert result is None


def test_dispatch_job_rejects_missing_document_id() -> None:
    job = _make_job(document_id=None)
    with pytest.raises(ValueError, match="missing document_id"):
        dispatch.dispatch_job(job)


def test_dispatch_job_rejects_unknown_job_type() -> None:
    job = _make_job(job_type="bogus")
    with pytest.raises(ValueError, match="Unknown job_type"):
        dispatch.dispatch_job(job)


def test_should_queue_ingestion_respects_active_runs_and_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    active_job_document_ids = {"doc-active-job"}

    def fake_has_active_ingestion_job(_session: Session, document_id: str) -> bool:
        return document_id in active_job_document_ids

    monkeypatch.setattr(queueing, "has_active_ingestion_job", fake_has_active_ingestion_job)
    session = cast("Session", object())

    assert queueing.should_queue_ingestion(session, _make_document(id="doc-new"), force=False) is True
    assert (
        queueing.should_queue_ingestion(
            session,
            _make_document(id="doc-complete", active_ingestion_run_id="run-1"),
            force=False,
        )
        is False
    )
    assert (
        queueing.should_queue_ingestion(
            session,
            _make_document(id="doc-active-job"),
            force=False,
        )
        is False
    )
    assert (
        queueing.should_queue_ingestion(
            session,
            _make_document(id="doc-complete", active_ingestion_run_id="run-1"),
            force=True,
        )
        is True
    )


def test_queue_ingestion_jobs_dispatches_and_deduplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_should_queue(_session: Session, document: models.Document, *, force: bool) -> bool:
        return document.id != "doc-skip"

    def fake_dispatch(job: models.Job) -> str:
        return f"task-{job.id}"

    monkeypatch.setattr(queueing, "should_queue_ingestion", fake_should_queue)
    monkeypatch.setattr(queueing, "dispatch_job", fake_dispatch)
    session = _FakeQueueSession()

    result = queueing.queue_ingestion_jobs(
        cast("Session", session),
        dataset_id="ds-1",
        documents=[
            _make_document(id="doc-queue"),
            _make_document(id="doc-queue"),
            _make_document(id="doc-skip"),
        ],
        force=False,
    )

    assert result.job_ids == ["job-1"]
    assert result.queued_document_ids == ["doc-queue"]
    assert result.skipped_document_ids == ["doc-skip"]
    assert session.added_jobs[0].celery_task_id == "task-job-1"
    assert session.commits == 2


def test_queue_ingestion_jobs_keeps_row_queued_when_dispatch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_dispatch(_job: models.Job) -> None:
        return None

    monkeypatch.setattr(queueing, "dispatch_job", fake_dispatch)
    session = _FakeQueueSession()

    result = queueing.queue_ingestion_jobs(
        cast("Session", session),
        dataset_id="ds-1",
        documents=[_make_document(id="doc-queue")],
        force=False,
    )

    assert result.job_ids == ["job-1"]
    assert result.queued_document_ids == ["doc-queue"]
    assert session.added_jobs[0].celery_task_id is None
    assert session.commits == 1


def test_document_serialization_prefers_active_ingestion_job_status() -> None:
    class _FakeSerializationSession:
        def __init__(self) -> None:
            self.calls = 0

        def scalar(self, _statement: object) -> str:
            self.calls += 1
            return "queued"

    session = _FakeSerializationSession()
    document = serialization.document_to_read(
        cast("Session", session),
        _make_document(active_ingestion_run_id="run-1"),
    )

    assert document.ingestion_status == "queued"
    assert session.calls == 1


def test_ingest_task_marks_job_running_before_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    progress_calls: list[tuple[str | None, str, int, str | None]] = []
    worker_session = _FakeWorkerSession()

    class _FakeSessionMaker:
        def __call__(self) -> _FakeWorkerSession:
            return worker_session

    def fake_commit_job_progress(
        job_id: str | None,
        *,
        status: str,
        progress: int,
        current_step: str | None,
        error: str | None = None,
    ) -> None:
        progress_calls.append((job_id, status, progress, current_step))

    def fake_run_document_ingestion(
        _session: Session,
        *,
        document_id: str,
        job_id: str | None = None,
        force: bool = False,
    ) -> models.IngestionRun:
        assert progress_calls == [("job-1", "running", 1, "worker picked up")]
        assert document_id == "doc-1"
        assert job_id == "job-1"
        assert force is True
        return cast("models.IngestionRun", SimpleNamespace(id="run-1"))

    monkeypatch.setattr(tasks, "commit_job_progress", fake_commit_job_progress)
    monkeypatch.setattr(tasks, "get_sessionmaker", lambda: _FakeSessionMaker())
    monkeypatch.setattr(tasks, "run_document_ingestion", fake_run_document_ingestion)

    run_id = tasks.ingest_document_task.run(document_id="doc-1", job_id="job-1", force=True)

    assert run_id == "run-1"
    assert worker_session.committed is True


def test_format_error_uses_class_name_for_empty_message() -> None:
    formatted = tasks._format_error(RuntimeError(""))
    assert formatted == "RuntimeError: RuntimeError"


def test_format_error_includes_message() -> None:
    formatted = tasks._format_error(ValueError("boom"))
    assert formatted == "ValueError: boom"


def test_celery_task_is_dead_treats_missing_id_as_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    assert sweeper._celery_task_is_dead(None) is True
    assert sweeper._celery_task_is_dead("") is True


def test_celery_task_is_dead_recognises_dead_states(monkeypatch: pytest.MonkeyPatch) -> None:
    states = iter(["PENDING", "REVOKED", "FAILURE", "STARTED", "SUCCESS"])

    class _FakeCelery:
        def AsyncResult(self, _task_id: str) -> SimpleNamespace:  # noqa: N802 - mirror Celery API
            return SimpleNamespace(state=next(states))

    monkeypatch.setattr(sweeper, "celery_app", _FakeCelery())

    # PENDING is treated as alive: with task_track_started=True it means the
    # message is in the queue but no worker has picked it up yet. Treating it
    # as dead would double-dispatch every healthy queued task.
    assert sweeper._celery_task_is_dead("t1") is False
    assert sweeper._celery_task_is_dead("t2") is True  # REVOKED
    assert sweeper._celery_task_is_dead("t3") is True  # FAILURE
    assert sweeper._celery_task_is_dead("t4") is False  # STARTED -> alive
    assert sweeper._celery_task_is_dead("t5") is True  # SUCCESS -> task finished, broker no longer holds it


def test_stale_queued_task_id_needs_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeCelery:
        def AsyncResult(self, _task_id: str) -> SimpleNamespace:  # noqa: N802 - mirror Celery API
            return SimpleNamespace(state="PENDING")

    monkeypatch.setattr(sweeper, "celery_app", _FakeCelery())
    now = datetime.now(UTC)
    stale = now - timedelta(seconds=sweeper.QUEUED_GRACE_SECONDS + 1)
    fresh = now - timedelta(seconds=sweeper.QUEUED_GRACE_SECONDS - 1)

    assert (
        sweeper._queued_job_needs_recovery(
            _make_job(celery_task_id="old-task", created_at=stale),
            now,
            sweeper.QUEUED_GRACE_SECONDS,
        )
        is True
    )
    assert (
        sweeper._queued_job_needs_recovery(
            _make_job(celery_task_id="new-task", created_at=fresh),
            now,
            sweeper.QUEUED_GRACE_SECONDS,
        )
        is False
    )
    assert (
        sweeper._queued_job_needs_recovery(
            _make_job(celery_task_id="new-task", created_at=fresh),
            now,
            0,
        )
        is True
    )


def test_redispatch_revokes_stale_existing_task(monkeypatch: pytest.MonkeyPatch) -> None:
    revoked: list[str] = []
    stale_job = _make_job(celery_task_id="old-task")

    class _FakeControl:
        def revoke(self, task_id: str, *, terminate: bool, signal: str) -> None:
            assert terminate is True
            assert signal == "SIGTERM"
            revoked.append(task_id)

    class _FakeCelery:
        control = _FakeControl()

    def fake_dispatch(job: models.Job) -> str:
        assert job.id == "job-1"
        return "new-task"

    monkeypatch.setattr(sweeper, "celery_app", _FakeCelery())
    monkeypatch.setattr(
        sweeper,
        "_collect_redispatch_candidates",
        lambda _session, _now, _queued_grace_seconds: [stale_job],
    )
    monkeypatch.setattr(sweeper, "dispatch_job", fake_dispatch)

    redispatched, exhausted = sweeper._redispatch_queued(cast("Session", object()), datetime.now(UTC), 0)

    assert (redispatched, exhausted) == (1, 0)
    assert revoked == ["old-task"]
    assert stale_job.retry_count == 1
    assert stale_job.celery_task_id == "new-task"


def test_queued_job_with_null_task_id_recovers_immediately() -> None:
    """A null ``celery_task_id`` proves dispatch never reached the broker, so
    the grace window shouldn't gate recovery. The operator-triggered sweep
    relies on this to redispatch jobs whose initial apply_async raised."""
    now = datetime.now(UTC)
    fresh_orphan = _make_job(celery_task_id=None, created_at=now)

    assert sweeper._queued_job_needs_recovery(fresh_orphan, now, sweeper.QUEUED_GRACE_SECONDS) is True
    assert sweeper._queued_job_needs_recovery(fresh_orphan, now, 0) is True


def test_run_sweep_does_not_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run_sweep`` is called inline from the API route, which owns the
    session lifecycle — the function must not commit on its own or it would
    end the FastAPI request session prematurely."""

    class _FakeSession:
        def __init__(self) -> None:
            self.commits = 0

        def commit(self) -> None:
            self.commits += 1

    monkeypatch.setattr(sweeper, "_redispatch_queued", lambda _s, _now, _grace: (2, 1))
    monkeypatch.setattr(sweeper, "_reap_silent_runners", lambda _s, _now, _hb: 3)
    session = _FakeSession()

    report = sweeper.run_sweep(
        cast("Session", session),
        now=datetime.now(UTC),
        queued_grace_seconds=0,
        heartbeat_seconds=600,
    )

    assert report == {"redispatched": 2, "exhausted": 1, "reaped": 3}
    assert session.commits == 0


def test_commit_job_progress_skips_cancelled_jobs() -> None:
    # Pure-logic guard test: TERMINAL_STATUSES is the source of truth for
    # what commit_job_progress refuses to overwrite.
    assert "cancelled" in job_state.TERMINAL_STATUSES
    assert "completed" in job_state.TERMINAL_STATUSES
    assert "completed_with_errors" in job_state.TERMINAL_STATUSES
    assert "running" not in job_state.TERMINAL_STATUSES
    assert "queued" not in job_state.TERMINAL_STATUSES
