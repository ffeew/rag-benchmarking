"""widen eval_runs.system_variant to fit multi-variant ablation names

The locked9 ablation joins 9 variant names into ``system_variant`` (188 chars),
which overflows the original ``VARCHAR(64)``. Widen to ``VARCHAR(512)`` so the
existing comma-join in ``api/routes/evaluations.py`` works for any reasonable
ablation matrix. The column is metadata-only (the authoritative variant list
lives in ``run_config.variants``), so widening is safe and lossless.

Revision ID: 0002_widen_system_variant
Revises: 0001_baseline_2026_05_17
Create Date: 2026-05-17 12:50:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_widen_system_variant"
down_revision = "0001_baseline_2026_05_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "eval_runs",
        "system_variant",
        existing_type=sa.String(length=64),
        type_=sa.String(length=512),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "eval_runs",
        "system_variant",
        existing_type=sa.String(length=512),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
