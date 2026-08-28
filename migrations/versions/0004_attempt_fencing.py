"""Persist lease fencing tokens on job attempts."""

from alembic import op
import sqlalchemy as sa

revision = "0004_attempt_fencing"
down_revision = "0003_job_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_attempts",
        sa.Column("lease_token", sa.String(length=36), nullable=True),
    )
    op.create_unique_constraint(
        "uq_job_attempts_lease_token", "job_attempts", ["lease_token"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_job_attempts_lease_token", "job_attempts", type_="unique"
    )
    op.drop_column("job_attempts", "lease_token")
