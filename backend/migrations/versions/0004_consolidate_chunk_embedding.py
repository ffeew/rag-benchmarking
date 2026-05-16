"""fold embeddings into chunks; strip duplicated chunk metadata keys

Drops the ``embeddings`` table and adds ``embedding_provider`` /
``embedding_model`` / ``embedding_dimension`` / ``embedding_vector`` columns to
``chunks``. The pre-existing 1:N capability (multiple embedding models per chunk
via ``uq_embeddings_chunk_provider_model``) was never exercised — the ingestion
pipeline keys ``IngestionRun`` dedup on ``embedding_model``, so each model
always produced its own chunks. Folding the columns removes one join from
every semantic query.

Also strips ``ticker`` / ``form_type`` / ``filing_date`` / ``report_period`` /
``parser`` / ``source_object_version`` from ``chunks.metadata`` — production
retrieval and API serialization read these from ``Document`` via the FK, so the
JSONB duplication was paid storage cost for no query benefit.

Backfill is lossless: existing ``embeddings`` rows are copied onto their
matching ``chunks`` row before the table is dropped. The migration aborts up
front if any chunk has multiple embeddings (which would lose data) or if any
stored dimension disagrees with ``vector(1024)``.

Revision ID: 0004_consolidate_chunk_embedding
Revises: 0003_dataset_override_lengths
Create Date: 2026-05-17 00:00:00.000000
"""

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision = "0004_consolidate_chunk_embedding"
down_revision = "0003_dataset_override_lengths"
branch_labels = None
depends_on = None


_REDUNDANT_CHUNK_METADATA_KEYS = (
    "ticker",
    "form_type",
    "filing_date",
    "report_period",
    "parser",
    "source_object_version",
)


def upgrade() -> None:
    bind = op.get_bind()

    duplicate = bind.execute(
        sa.text(
            "SELECT chunk_id, COUNT(*) AS n FROM embeddings "
            "GROUP BY chunk_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            f"chunk_id={duplicate[0]} has {duplicate[1]} embeddings; lossless 1:1 "
            "backfill is impossible. Drop the extras manually (keeping the one matching "
            "the active embedding model) and re-run the migration."
        )

    bad_dim = bind.execute(
        sa.text("SELECT dimension FROM embeddings WHERE dimension != 1024 LIMIT 1")
    ).first()
    if bad_dim is not None:
        raise RuntimeError(
            f"embeddings.dimension={bad_dim[0]} != 1024 found; the new "
            "chunks.embedding_vector column is vector(1024). Resolve mismatched rows "
            "(re-embed or delete) and re-run the migration."
        )

    op.add_column("chunks", sa.Column("embedding_provider", sa.String(length=64), nullable=True))
    op.add_column("chunks", sa.Column("embedding_model", sa.String(length=255), nullable=True))
    op.add_column("chunks", sa.Column("embedding_dimension", sa.Integer(), nullable=True))
    op.add_column(
        "chunks",
        sa.Column("embedding_vector", pgvector.sqlalchemy.vector.VECTOR(1024), nullable=True),
    )

    op.execute(
        """
        UPDATE chunks AS c
        SET embedding_provider = e.provider,
            embedding_model = e.model,
            embedding_dimension = e.dimension,
            embedding_vector = e.vector
        FROM embeddings AS e
        WHERE e.chunk_id = c.id
        """
    )

    op.execute(
        "UPDATE chunks "
        "SET metadata = metadata - ARRAY["
        "'ticker','form_type','filing_date','report_period','parser','source_object_version'"
        "]::text[] "
        "WHERE metadata ?| ARRAY["
        "'ticker','form_type','filing_date','report_period','parser','source_object_version'"
        "]::text[]"
    )

    op.drop_table("embeddings")

    op.create_index("ix_chunks_embedding_model", "chunks", ["embedding_model"])
    op.execute(
        "CREATE INDEX ix_chunks_embedding_vector_hnsw "
        "ON chunks USING hnsw (embedding_vector vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_embedding_vector_hnsw", table_name="chunks")
    op.drop_index("ix_chunks_embedding_model", table_name="chunks")

    op.create_table(
        "embeddings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("vector", pgvector.sqlalchemy.vector.VECTOR(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_id", "provider", "model", name="uq_embeddings_chunk_provider_model"),
    )
    op.create_index("ix_embeddings_chunk_id", "embeddings", ["chunk_id"])
    op.create_index("ix_embeddings_model", "embeddings", ["model"])
    op.execute(
        "CREATE INDEX ix_embeddings_vector_hnsw "
        "ON embeddings USING hnsw (vector vector_cosine_ops)"
    )

    # Re-create one embeddings row per chunk that has a vector. gen_random_uuid()
    # is in core Postgres 13+; cast its uuid result to text to match the column type.
    op.execute(
        """
        INSERT INTO embeddings (id, chunk_id, provider, model, dimension, vector, created_at, updated_at)
        SELECT gen_random_uuid()::text, id, embedding_provider, embedding_model,
               embedding_dimension, embedding_vector, created_at, updated_at
        FROM chunks
        WHERE embedding_vector IS NOT NULL
          AND embedding_provider IS NOT NULL
          AND embedding_model IS NOT NULL
          AND embedding_dimension IS NOT NULL
        """
    )

    op.drop_column("chunks", "embedding_vector")
    op.drop_column("chunks", "embedding_dimension")
    op.drop_column("chunks", "embedding_model")
    op.drop_column("chunks", "embedding_provider")
    # The stripped chunks.metadata keys (ticker/form_type/filing_date/report_period/
    # parser/source_object_version) are NOT restored by this downgrade. They are
    # derivable from documents/ingestion_runs at retrieval time; a follow-up
    # data script can repopulate them if required.
