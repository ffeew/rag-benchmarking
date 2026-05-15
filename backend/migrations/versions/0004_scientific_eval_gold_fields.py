"""scientific eval gold fields

Revision ID: 0004_scientific_eval_gold_fields
Revises: 0003_eval_metric_extensions
Create Date: 2026-05-15 11:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_scientific_eval_gold_fields"
down_revision = "0003_eval_metric_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_cases",
        sa.Column("expected_answer_spec", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "eval_cases",
        sa.Column("expected_evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "eval_cases",
        sa.Column("verification_status", sa.String(length=16), nullable=False, server_default="draft"),
    )
    op.add_column("eval_cases", sa.Column("verified_by", sa.String(length=128), nullable=True))
    op.add_column("eval_cases", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "eval_cases",
        sa.Column("gold_version", sa.String(length=32), nullable=False, server_default="v1"),
    )
    op.create_index("ix_eval_cases_verification_status", "eval_cases", ["verification_status"])

    op.alter_column("eval_cases", "expected_answer_spec", server_default=None)
    op.alter_column("eval_cases", "expected_evidence", server_default=None)
    op.alter_column("eval_cases", "verification_status", server_default=None)
    op.alter_column("eval_cases", "gold_version", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_eval_cases_verification_status", table_name="eval_cases")
    op.drop_column("eval_cases", "gold_version")
    op.drop_column("eval_cases", "verified_at")
    op.drop_column("eval_cases", "verified_by")
    op.drop_column("eval_cases", "verification_status")
    op.drop_column("eval_cases", "expected_evidence")
    op.drop_column("eval_cases", "expected_answer_spec")
