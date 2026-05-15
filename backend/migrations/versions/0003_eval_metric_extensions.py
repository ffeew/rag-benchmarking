"""eval metric extensions

Revision ID: 0003_eval_metric_extensions
Revises: 0002_job_fault_tolerance
Create Date: 2026-05-15 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_eval_metric_extensions"
down_revision = "0002_job_fault_tolerance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("eval_cases", sa.Column("case_key", sa.String(length=64), nullable=True))
    op.add_column("eval_cases", sa.Column("category", sa.String(length=64), nullable=True))
    op.add_column("eval_cases", sa.Column("difficulty", sa.String(length=16), nullable=True))
    op.create_index(
        "uq_eval_cases_dataset_case_key",
        "eval_cases",
        ["dataset_id", "case_key"],
        unique=True,
        postgresql_where=sa.text("case_key IS NOT NULL"),
    )
    op.create_index("ix_eval_cases_category", "eval_cases", ["category"])
    op.create_index("ix_eval_cases_difficulty", "eval_cases", ["difficulty"])

    op.add_column("eval_results", sa.Column("usage", postgresql.JSONB(), nullable=True))
    op.add_column("eval_results", sa.Column("cost_estimate", postgresql.JSONB(), nullable=True))
    op.add_column("eval_results", sa.Column("latency_ms", sa.Integer(), nullable=True))

    op.add_column("query_traces", sa.Column("usage_summary", postgresql.JSONB(), nullable=True))
    op.add_column("query_traces", sa.Column("cost_estimate_usd", sa.Numeric(precision=10, scale=6), nullable=True))

    op.create_index("ix_parsed_pages_parser", "parsed_pages", ["parser"])


def downgrade() -> None:
    op.drop_index("ix_parsed_pages_parser", table_name="parsed_pages")

    op.drop_column("query_traces", "cost_estimate_usd")
    op.drop_column("query_traces", "usage_summary")

    op.drop_column("eval_results", "latency_ms")
    op.drop_column("eval_results", "cost_estimate")
    op.drop_column("eval_results", "usage")

    op.drop_index("ix_eval_cases_difficulty", table_name="eval_cases")
    op.drop_index("ix_eval_cases_category", table_name="eval_cases")
    op.drop_index("uq_eval_cases_dataset_case_key", table_name="eval_cases")
    op.drop_column("eval_cases", "difficulty")
    op.drop_column("eval_cases", "category")
    op.drop_column("eval_cases", "case_key")
