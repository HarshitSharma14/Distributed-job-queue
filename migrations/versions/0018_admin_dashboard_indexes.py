"""Add indexes for global Admin dashboard queries."""

from alembic import op


revision = "0018_admin_dashboard_indexes"
down_revision = "0017_worker_dashboard_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_jobs_status_created_id",
        "jobs",
        ["status", "created_at", "id"],
    )
    op.create_index(
        "ix_jobs_queue_status",
        "jobs",
        ["queue", "status"],
    )
    op.create_index(
        "ix_workers_status_registered_id",
        "workers",
        ["status", "registered_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workers_status_registered_id", table_name="workers")
    op.drop_index("ix_jobs_queue_status", table_name="jobs")
    op.drop_index("ix_jobs_status_created_id", table_name="jobs")
