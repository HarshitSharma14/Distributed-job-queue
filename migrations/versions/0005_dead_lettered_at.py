"""Record durable dead-letter state and timestamp."""

from alembic import op
import sqlalchemy as sa

revision = "0005_dead_lettered_at"
down_revision = "0004_attempt_fencing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE jobs
        SET status = 'DEAD_LETTERED',
            dead_lettered_at = COALESCE(updated_at, NOW())
        WHERE status = 'FAILED'
          AND attempts >= max_attempts
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE jobs
        SET status = 'FAILED'
        WHERE status = 'DEAD_LETTERED'
        """
    )
    op.drop_column("jobs", "dead_lettered_at")
