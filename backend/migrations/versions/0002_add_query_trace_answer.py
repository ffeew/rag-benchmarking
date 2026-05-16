"""add answer column to query_traces

The ``QueryTrace.answer`` column was added to the SQLAlchemy model after the
squashed baseline shipped, but no migration carried it onto already-migrated
databases. This revision brings them back in sync.

Revision ID: 0002_query_trace_answer
Revises: 0001_baseline_2026_05_17
Create Date: 2026-05-17 20:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_query_trace_answer"
down_revision = "0001_baseline_2026_05_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("query_traces", sa.Column("answer", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("query_traces", "answer")
