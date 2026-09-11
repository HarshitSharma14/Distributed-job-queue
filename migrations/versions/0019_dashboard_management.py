"""Dashboard accounts, durable queue controls, replay lineage and audit."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019_dashboard_management"
down_revision = "0018_admin_dashboard_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "password_change_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "jobs", sa.Column("replay_of_job_id", sa.String(36), sa.ForeignKey("jobs.id"))
    )
    op.add_column(
        "jobs",
        sa.Column("replay_requested_by", sa.String(36), sa.ForeignKey("users.id")),
    )
    op.create_index("ix_jobs_replay_of_job_id", "jobs", ["replay_of_job_id"])
    op.create_table(
        "queue_controls",
        sa.Column("queue", sa.String(100), primary_key=True),
        sa.Column(
            "paused", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id")),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_events_target_id", "audit_events", ["target_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade():
    op.drop_table("audit_events")
    op.drop_table("queue_controls")
    op.drop_index("ix_jobs_replay_of_job_id", "jobs")
    op.drop_column("jobs", "replay_requested_by")
    op.drop_column("jobs", "replay_of_job_id")
    op.drop_column("users", "password_change_required")
