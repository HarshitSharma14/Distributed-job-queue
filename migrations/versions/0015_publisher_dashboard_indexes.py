"""Add indexes for Publisher dashboard queries."""

from alembic import op


revision = "0015_publisher_dashboard_indexes"
down_revision = "0014_job_type_version_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_jobs_publisher_created_id",
        "jobs",
        ["publisher_id", "created_at", "id"],
    )
    op.create_index(
        "ix_jobs_publisher_status",
        "jobs",
        ["publisher_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_publisher_status", table_name="jobs")
    op.drop_index("ix_jobs_publisher_created_id", table_name="jobs")
