"""Add indexes for Producer dashboard queries."""

from alembic import op


revision = "0016_producer_dashboard_indexes"
down_revision = "0015_publisher_dashboard_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_jobs_producer_created_id",
        "jobs",
        ["producer_id", "created_at", "id"],
    )
    op.create_index(
        "ix_jobs_producer_status",
        "jobs",
        ["producer_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_producer_status", table_name="jobs")
    op.drop_index("ix_jobs_producer_created_id", table_name="jobs")
