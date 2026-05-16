"""tighten dataset override column lengths

Aligns ``datasets.domain_label`` / ``hyde_style_hint`` / ``citation_label_template``
column types with the Pydantic ``max_length`` constraints declared on ``DatasetCreate``
/ ``DatasetUpdate`` (512 / 2048 / 256). Previously the columns were unbounded ``Text``
while Pydantic capped them; this migration enforces the same cap at the DB layer so
direct SQL writes cannot bypass the contract.

Revision ID: 0003_dataset_override_lengths
Revises: 0002_dataset_domain_overrides
Create Date: 2026-05-16 23:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_dataset_override_lengths"
down_revision = "0002_dataset_domain_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "datasets",
        "domain_label",
        existing_type=sa.Text(),
        type_=sa.String(length=512),
        existing_nullable=True,
    )
    op.alter_column(
        "datasets",
        "hyde_style_hint",
        existing_type=sa.Text(),
        type_=sa.String(length=2048),
        existing_nullable=True,
    )
    op.alter_column(
        "datasets",
        "citation_label_template",
        existing_type=sa.Text(),
        type_=sa.String(length=256),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "datasets",
        "citation_label_template",
        existing_type=sa.String(length=256),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "datasets",
        "hyde_style_hint",
        existing_type=sa.String(length=2048),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "datasets",
        "domain_label",
        existing_type=sa.String(length=512),
        type_=sa.Text(),
        existing_nullable=True,
    )
