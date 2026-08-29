"""Add indexes for Worker dashboard queries."""

from alembic import op


revision = "0017_worker_dashboard_indexes"
down_revision = "0016_producer_dashboard_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_jobs_worker_status",
        "jobs",
        ["worker_id", "status"],
    )
    op.create_index(
        "ix_job_attempts_worker_started_id",
        "job_attempts",
        ["worker_id", "started_at", "id"],
    )
    op.create_index(
        "ix_job_attempts_worker_status",
        "job_attempts",
        ["worker_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_attempts_worker_status", table_name="job_attempts")
    op.drop_index("ix_job_attempts_worker_started_id", table_name="job_attempts")
    op.drop_index("ix_jobs_worker_status", table_name="jobs")
