"""Shared pytest fixtures for FastAPI route tests.

Uses testcontainers to spin up a real Postgres + pgvector instance (same image as
docker-compose: pgvector/pgvector:pg17). This keeps the test schema, indexes, JSONB
operators, and vector queries identical to production — no dialect workarounds.

The container starts once per pytest session and is reused across tests. Per-test
isolation is provided by truncating all tables in the function-scoped `db_session`
fixture (faster than rebuilding the schema each time).
"""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rag_common.db import models
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer


def _ensure_settings_env() -> None:
    """Set env vars that Settings requires *before* it's imported by anything."""
    os.environ.setdefault("API_BEARER_TOKEN", "test-token")
    os.environ.setdefault("ALLOW_MOCK_PROVIDERS", "true")


_ensure_settings_env()


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    container = PostgresContainer(
        image="pgvector/pgvector:pg17",
        username="rag",
        password="rag",
        dbname="rag",
        driver="psycopg",
    )
    container.start()
    try:
        # Patch settings + env to point at the container before any code reads them.
        url = container.get_connection_url()
        os.environ["DATABASE_URL"] = url
        from rag_common.config import get_settings

        get_settings.cache_clear()
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def engine(postgres_container: PostgresContainer) -> Generator[Engine, None, None]:
    engine = create_engine(postgres_container.get_connection_url(), future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    models.Base.metadata.create_all(engine)
    # Recreate the partial unique index from migration 0003 — create_all doesn't
    # emit it because SQLAlchemy doesn't model partial indexes natively.
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_eval_cases_dataset_case_key "
                "ON eval_cases (dataset_id, case_key) WHERE case_key IS NOT NULL"
            )
        )
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Generator[Session, None, None]:
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        # TRUNCATE ... RESTART IDENTITY CASCADE clears all tables in one statement,
        # respecting foreign keys. Faster than per-table DELETE.
        table_names = ", ".join(table.name for table in models.Base.metadata.sorted_tables)
        if table_names:
            session.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
            session.commit()
        session.close()


@pytest.fixture
def app(db_session: Session) -> Generator[FastAPI, None, None]:
    """Build the FastAPI app with auth + DB dependencies overridden to use the test session."""
    from rag_benchmarking.api.deps import db_session as db_session_dep, require_bearer_token

    # Late import so the patched DATABASE_URL is in place when the app is built.
    from rag_benchmarking.main import app as real_app

    def _session_override() -> Generator[Session, None, None]:
        yield db_session

    def _auth_override() -> None:
        return None

    real_app.dependency_overrides[db_session_dep] = _session_override
    real_app.dependency_overrides[require_bearer_token] = _auth_override
    try:
        yield real_app
    finally:
        real_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


# ---------------------- factories ----------------------

@pytest.fixture
def seed_dataset(db_session: Session) -> models.Dataset:
    dataset = models.Dataset(
        name="test-dataset",
        description="Dataset for route tests",
        default_query_settings={},
    )
    db_session.add(dataset)
    db_session.commit()
    db_session.refresh(dataset)
    return dataset


@pytest.fixture
def seed_document(db_session: Session, seed_dataset: models.Dataset) -> models.Document:
    document = cast(
        models.Document,
        models.Document(
            dataset_id=seed_dataset.id,
            ticker="AAPL",
            form_type="10-K",
            checksum="abc123",
            minio_bucket="bucket",
            minio_key="raw/x.pdf",
            byte_size=42,
        ),
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)
    return document


@pytest.fixture
def seed_eval_case(db_session: Session, seed_dataset: models.Dataset) -> models.EvalCase:
    case = models.EvalCase(
        dataset_id=seed_dataset.id,
        case_key="seed_q1",
        category="single_company_lookup",
        difficulty="easy",
        question="What was Apple's revenue?",
        expected_answer=None,
        expected_citations=[{"ticker": "AAPL", "form_type": "10-K"}],
        tags=["revenue"],
    )
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)
    return case
