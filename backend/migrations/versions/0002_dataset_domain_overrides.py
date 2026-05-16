"""dataset domain-adaptive retrieval overrides

Adds nullable columns to ``datasets`` so each row can override the SEC-flavored
prompt identity, valid form types, metric hints, HyDE style cue, citation label
template, and verifier stopwords. Nulls resolve to the SEC defaults in
``rag_retrieval.dataset_config``, so existing rows behave identically.

Revision ID: 0002_dataset_domain_overrides
Revises: 0001_initial_schema
Create Date: 2026-05-16 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_dataset_domain_overrides"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("domain_label", sa.Text(), nullable=True))
    op.add_column("datasets", sa.Column("entity_label", sa.String(length=64), nullable=True))
    op.add_column("datasets", sa.Column("valid_forms", postgresql.JSONB(), nullable=True))
    op.add_column("datasets", sa.Column("metric_terms", postgresql.JSONB(), nullable=True))
    op.add_column("datasets", sa.Column("hyde_style_hint", sa.Text(), nullable=True))
    op.add_column("datasets", sa.Column("citation_label_template", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("datasets", "citation_label_template")
    op.drop_column("datasets", "hyde_style_hint")
    op.drop_column("datasets", "metric_terms")
    op.drop_column("datasets", "valid_forms")
    op.drop_column("datasets", "entity_label")
    op.drop_column("datasets", "domain_label")
