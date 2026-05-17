from __future__ import annotations

import uuid
from datetime import date, datetime  # noqa: TC003 - SQLAlchemy resolves postponed Mapped annotations at runtime.
from decimal import Decimal  # noqa: TC003 - same reason as above for Numeric columns.
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from rag_common.constants import EMBEDDING_VECTOR_DIMENSION
from rag_common.enums import (
    IngestionRunStatus,
    JobStatus,
    RetrievalMode,
    VerificationStatus,
)


def uuid_str() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Dataset(TimestampMixin, Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    default_query_settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    # Domain-adaptive retrieval config; nulls fall back to per-field defaults in
    # rag_retrieval.dataset_config.load_dataset_config (SEC defaults for valid_forms /
    # metric_terms / citation_label_template / domain_label / entity_label; None for
    # hyde_style_hint). Column lengths mirror the Pydantic max_length on
    # DatasetCreate / DatasetUpdate so the contract is enforced at both layers.
    domain_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    entity_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valid_forms: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    metric_terms: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    hyde_style_hint: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    citation_label_template: Mapped[str | None] = mapped_column(String(256), nullable=True)

    documents: Mapped[list[Document]] = relationship(back_populates="dataset")


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("dataset_id", "checksum", name="uq_documents_dataset_checksum"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    company_name: Mapped[str | None] = mapped_column(String(255))
    form_type: Mapped[str] = mapped_column(String(16), index=True)
    filing_date: Mapped[date | None] = mapped_column(Date, index=True)
    report_period: Mapped[date | None] = mapped_column(Date, index=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    minio_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    minio_key: Mapped[str] = mapped_column(Text, nullable=False)
    minio_version_id: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    active_ingestion_run_id: Mapped[str | None] = mapped_column(String(36), index=True)

    dataset: Mapped[Dataset] = relationship(back_populates="documents")
    ingestion_runs: Mapped[list[IngestionRun]] = relationship(back_populates="document")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="document")


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default=JobStatus.QUEUED)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_step: Mapped[str | None] = mapped_column(String(255))
    celery_task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    dataset_id: Mapped[str | None] = mapped_column(String(36), index=True)
    document_id: Mapped[str | None] = mapped_column(String(36), index=True)
    eval_run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionRun(TimestampMixin, Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    parser_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    chunking_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=IngestionRunStatus.QUEUED, index=True)
    timings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="ingestion_runs")
    parsed_pages: Mapped[list[ParsedPage]] = relationship(back_populates="ingestion_run")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="ingestion_run")


class ParsedPage(TimestampMixin, Base):
    __tablename__ = "parsed_pages"
    __table_args__ = (UniqueConstraint("ingestion_run_id", "page_number", name="uq_parsed_pages_run_page"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    parser: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_key: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    source_minio_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_minio_version_id: Mapped[str | None] = mapped_column(Text)

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="parsed_pages")


class Chunk(TimestampMixin, Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    ingestion_run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    contains_table: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    source_offsets: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # Nullable so the existing two-phase write survives: chunks commit before the
    # embedding API call, the per-batch UPDATE fills these in, and a failed batch
    # leaves NULLs that the retrieval query filters out.
    embedding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_vector: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_VECTOR_DIMENSION), nullable=True)

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="chunks")
    document: Mapped[Document] = relationship(back_populates="chunks")


class QueryTrace(TimestampMixin, Base):
    __tablename__ = "query_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    user_question: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    retrieval_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    verifier_result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    model_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    final_answer_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    timings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    usage_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    cost_estimate_usd: Mapped[Decimal | None] = mapped_column(Numeric(precision=10, scale=6), nullable=True)

    citations: Mapped[list[Citation]] = relationship(back_populates="trace")


class Citation(TimestampMixin, Base):
    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    trace_id: Mapped[str] = mapped_column(ForeignKey("query_traces.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    citation_label: Mapped[str] = mapped_column(String(128), nullable=False)
    minio_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    minio_key: Mapped[str] = mapped_column(Text, nullable=False)
    minio_version_id: Mapped[str | None] = mapped_column(Text)

    trace: Mapped[QueryTrace] = relationship(back_populates="citations")


class EvalCase(TimestampMixin, Base):
    __tablename__ = "eval_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    case_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    expected_citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    expected_answer_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    expected_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=VerificationStatus.DRAFT, index=True
    )
    verified_by: Mapped[str | None] = mapped_column(String(128))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gold_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)


class EvalRun(TimestampMixin, Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.QUEUED, index=True)
    run_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    system_variant: Mapped[str] = mapped_column(String(512), nullable=False, default=RetrievalMode.FULL_AGENTIC)
    model_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    results: Mapped[list[EvalResult]] = relationship(back_populates="eval_run")


class EvalResult(TimestampMixin, Base):
    __tablename__ = "eval_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    eval_run_id: Mapped[str] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True)
    eval_case_id: Mapped[str | None] = mapped_column(ForeignKey("eval_cases.id", ondelete="SET NULL"))
    retrieval_mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    variant_name: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    answer: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(ForeignKey("query_traces.id", ondelete="SET NULL"))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    cost_estimate: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    eval_run: Mapped[EvalRun] = relationship(back_populates="results")
