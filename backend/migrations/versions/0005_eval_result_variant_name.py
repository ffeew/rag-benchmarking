"""eval_result variant_name for component-lesion ablations

Revision ID: 0005_eval_result_variant_name
Revises: 0004_scientific_eval_gold_fields
Create Date: 2026-05-16 18:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_eval_result_variant_name"
down_revision = "0004_scientific_eval_gold_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_results",
        sa.Column("variant_name", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_eval_results_variant_name", "eval_results", ["variant_name"])
    # Backfill legacy rows: variant_name defaults to the underlying retrieval_mode
    # literal so paired analysis on historical runs still has a join key.
    op.execute("UPDATE eval_results SET variant_name = retrieval_mode WHERE variant_name IS NULL")


def downgrade() -> None:
    op.drop_index("ix_eval_results_variant_name", table_name="eval_results")
    op.drop_column("eval_results", "variant_name")
