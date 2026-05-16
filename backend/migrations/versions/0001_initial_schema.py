"""initial schema (squashed baseline 2026-05-17)

Final consolidated schema produced by squashing migrations
0001_initial_schema, 0002_dataset_domain_overrides, 0003_dataset_override_lengths,
and 0004_consolidate_chunk_embedding into a single baseline:

- Dataset has the domain-adaptive override columns (``domain_label``,
  ``entity_label``, ``valid_forms``, ``metric_terms``, ``hyde_style_hint``,
  ``citation_label_template``) with the Pydantic-aligned VARCHAR sizes.
- Chunk owns ``embedding_provider`` / ``embedding_model`` /
  ``embedding_dimension`` / ``embedding_vector`` directly; the old
  ``embeddings`` table no longer exists, and the HNSW index lives on
  ``chunks.embedding_vector``.
- Document, IngestionRun, ParsedPage, Job, QueryTrace, Citation, EvalCase,
  EvalRun, EvalResult are unchanged from the pre-squash baseline.

**Existing databases**: anyone whose ``alembic_version`` is one of
``0001_initial_schema`` / ``0002_dataset_domain_overrides`` /
``0003_dataset_override_lengths`` / ``0004_consolidate_chunk_embedding`` must
re-stamp once::

    alembic stamp 0001_baseline_2026_05_17 --purge

The schema is already in its final shape on those databases, so no DDL
needs to run. ``--purge`` clears the now-orphaned revision row before
re-stamping.

Revision ID: 0001_baseline_2026_05_17
Revises:
Create Date: 2026-05-17 01:00:00.000000
"""

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_baseline_2026_05_17"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "datasets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_query_settings", postgresql.JSONB(), nullable=False),
        sa.Column("domain_label", sa.String(length=512), nullable=True),
        sa.Column("entity_label", sa.String(length=64), nullable=True),
        sa.Column("valid_forms", postgresql.JSONB(), nullable=True),
        sa.Column("metric_terms", postgresql.JSONB(), nullable=True),
        sa.Column("hyde_style_hint", sa.String(length=2048), nullable=True),
        sa.Column("citation_label_template", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("current_step", sa.String(length=255), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("dataset_id", sa.String(length=36), nullable=True),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("eval_run_id", sa.String(length=36), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("form_type", sa.String(length=16), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("report_period", sa.Date(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_quarter", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("minio_bucket", sa.String(length=128), nullable=False),
        sa.Column("minio_key", sa.Text(), nullable=False),
        sa.Column("minio_version_id", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("active_ingestion_run_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "checksum", name="uq_documents_dataset_checksum"),
    )
    op.create_table(
        "eval_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("case_key", sa.String(length=64), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("difficulty", sa.String(length=16), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text(), nullable=True),
        sa.Column("expected_citations", postgresql.JSONB(), nullable=False),
        sa.Column("expected_answer_spec", postgresql.JSONB(), nullable=False),
        sa.Column("expected_evidence", postgresql.JSONB(), nullable=False),
        sa.Column("verification_status", sa.String(length=16), nullable=False),
        sa.Column("verified_by", sa.String(length=128), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gold_version", sa.String(length=32), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("run_config", postgresql.JSONB(), nullable=False),
        sa.Column("system_variant", sa.String(length=64), nullable=False),
        sa.Column("model_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("errors", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("parser_config", postgresql.JSONB(), nullable=False),
        sa.Column("chunking_config", postgresql.JSONB(), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("timings", postgresql.JSONB(), nullable=False),
        sa.Column("counts", postgresql.JSONB(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "parsed_pages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("parser", sa.String(length=64), nullable=False),
        sa.Column("artifact_key", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_char_count", sa.Integer(), nullable=False),
        sa.Column("table_count", sa.Integer(), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(), nullable=False),
        sa.Column("source_minio_key", sa.Text(), nullable=False),
        sa.Column("source_minio_version_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingestion_run_id"], ["ingestion_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ingestion_run_id", "page_number", name="uq_parsed_pages_run_page"),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("contains_table", sa.Boolean(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("source_offsets", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        # Embedding columns live on chunks directly; the old separate ``embeddings``
        # table never used its (chunk_id, provider, model) 1:N capability because the
        # ingestion pipeline keys IngestionRun dedup on the embedding model, so each
        # model produced its own chunk set. Nullable: chunks commit before the
        # embedding API call so retries don't waste chunk work.
        sa.Column("embedding_provider", sa.String(length=64), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
        sa.Column("embedding_vector", pgvector.sqlalchemy.vector.VECTOR(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingestion_run_id"], ["ingestion_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "query_traces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("user_question", sa.Text(), nullable=False),
        sa.Column("retrieval_mode", sa.String(length=32), nullable=False),
        sa.Column("plan", postgresql.JSONB(), nullable=False),
        sa.Column("retrieval_calls", postgresql.JSONB(), nullable=False),
        sa.Column("verifier_result", postgresql.JSONB(), nullable=False),
        sa.Column("model_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("final_answer_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("timings", postgresql.JSONB(), nullable=False),
        sa.Column("usage_summary", postgresql.JSONB(), nullable=True),
        sa.Column("cost_estimate_usd", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "citations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("citation_label", sa.String(length=128), nullable=False),
        sa.Column("minio_bucket", sa.String(length=128), nullable=False),
        sa.Column("minio_key", sa.Text(), nullable=False),
        sa.Column("minio_version_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trace_id"], ["query_traces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "eval_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("eval_run_id", sa.String(length=36), nullable=False),
        sa.Column("eval_case_id", sa.String(length=36), nullable=True),
        sa.Column("retrieval_mode", sa.String(length=32), nullable=False),
        sa.Column("variant_name", sa.String(length=64), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=36), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("usage", postgresql.JSONB(), nullable=True),
        sa.Column("cost_estimate", postgresql.JSONB(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["eval_case_id"], ["eval_cases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["eval_run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trace_id"], ["query_traces.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    for table_name, column_names in {
        "documents": [
            "dataset_id",
            "ticker",
            "form_type",
            "filing_date",
            "report_period",
            "checksum",
            "active_ingestion_run_id",
        ],
        "jobs": ["job_type", "status", "celery_task_id", "dataset_id", "document_id", "eval_run_id"],
        "ingestion_runs": ["dataset_id", "document_id", "job_id", "status"],
        "parsed_pages": ["ingestion_run_id", "document_id", "page_number", "parser"],
        "chunks": [
            "ingestion_run_id",
            "document_id",
            "page_start",
            "page_end",
            "contains_table",
            "is_active",
            "embedding_model",
        ],
        "query_traces": ["dataset_id"],
        "citations": ["trace_id", "chunk_id", "document_id"],
        "eval_cases": ["dataset_id", "category", "difficulty", "verification_status"],
        "eval_runs": ["dataset_id", "job_id", "status"],
        "eval_results": ["eval_run_id", "retrieval_mode", "variant_name"],
    }.items():
        for column_name in column_names:
            op.create_index(f"ix_{table_name}_{column_name}", table_name, [column_name])

    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at"])
    op.create_index("ix_jobs_status_last_heartbeat_at", "jobs", ["status", "last_heartbeat_at"])
    op.create_index(
        "uq_eval_cases_dataset_case_key",
        "eval_cases",
        ["dataset_id", "case_key"],
        unique=True,
        postgresql_where=sa.text("case_key IS NOT NULL"),
    )

    op.execute(
        "CREATE INDEX ix_chunks_normalized_text_fts ON chunks USING gin (to_tsvector('english', normalized_text))"
    )
    op.execute("CREATE INDEX ix_chunks_embedding_vector_hnsw ON chunks USING hnsw (embedding_vector vector_cosine_ops)")


def downgrade() -> None:
    op.drop_table("eval_results")
    op.drop_table("citations")
    op.drop_table("query_traces")
    op.drop_table("chunks")
    op.drop_table("parsed_pages")
    op.drop_table("ingestion_runs")
    op.drop_table("eval_runs")
    op.drop_table("eval_cases")
    op.drop_table("documents")
    op.drop_table("jobs")
    op.drop_table("datasets")
    op.execute("DROP EXTENSION IF EXISTS vector")
