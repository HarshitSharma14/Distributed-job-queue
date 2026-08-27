"""Add durable job submission idempotency."""

from alembic import op
import sqlalchemy as sa

revision = "0003_job_idempotency"
down_revision = "0002_durable_leases_and_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("idempotency_key", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "jobs", sa.Column("request_hash", sa.String(length=64), nullable=True)
    )
    op.create_unique_constraint(
        "uq_jobs_idempotency_key", "jobs", ["idempotency_key"]
    )
    op.create_check_constraint(
        "ck_jobs_idempotency_pair",
        "jobs",
        "(idempotency_key IS NULL AND request_hash IS NULL) OR "
        "(idempotency_key IS NOT NULL AND request_hash IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_jobs_idempotency_pair", "jobs", type_="check")
    op.drop_constraint("uq_jobs_idempotency_key", "jobs", type_="unique")
    op.drop_column("jobs", "request_hash")
    op.drop_column("jobs", "idempotency_key")
