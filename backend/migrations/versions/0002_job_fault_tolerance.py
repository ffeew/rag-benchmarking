"""job fault tolerance columns and indexes

Revision ID: 0002_job_fault_tolerance
Revises: 0001_initial_schema
Create Date: 2026-05-14 19:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_job_fault_tolerance"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "jobs",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_jobs_status_created_at",
        "jobs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_jobs_status_last_heartbeat_at",
        "jobs",
        ["status", "last_heartbeat_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_status_last_heartbeat_at", table_name="jobs")
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_column("jobs", "last_heartbeat_at")
    op.drop_column("jobs", "retry_count")
