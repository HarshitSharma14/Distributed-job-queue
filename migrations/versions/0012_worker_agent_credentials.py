"""Add one-time Worker enrollment and per-agent credentials."""

from alembic import op
import sqlalchemy as sa


revision = "0012_worker_agent_credentials"
down_revision = "0011_verified_handler_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_enrollments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("job_type_id", sa.String(length=36), nullable=False),
        sa.Column("token_prefix", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_type_id"], ["job_types.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_worker_enrollments_token_hash"),
    )
    op.create_index("ix_worker_enrollments_owner_user_id", "worker_enrollments", ["owner_user_id"])
    op.create_index("ix_worker_enrollments_job_type_id", "worker_enrollments", ["job_type_id"])
    op.create_index("ix_worker_enrollments_expires_at", "worker_enrollments", ["expires_at"])

    op.create_table(
        "worker_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("worker_id", sa.String(length=100), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("enrollment_id", sa.String(length=36), nullable=False),
        sa.Column("token_prefix", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["enrollment_id"], ["worker_enrollments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("enrollment_id", name="uq_worker_credentials_enrollment_id"),
        sa.UniqueConstraint("token_hash", name="uq_worker_credentials_token_hash"),
    )
    op.create_index("ix_worker_credentials_worker_id", "worker_credentials", ["worker_id"])
    op.create_index("ix_worker_credentials_owner_user_id", "worker_credentials", ["owner_user_id"])
    op.create_index("ix_worker_credentials_expires_at", "worker_credentials", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_worker_credentials_expires_at", table_name="worker_credentials")
    op.drop_index("ix_worker_credentials_owner_user_id", table_name="worker_credentials")
    op.drop_index("ix_worker_credentials_worker_id", table_name="worker_credentials")
    op.drop_table("worker_credentials")
    op.drop_index("ix_worker_enrollments_expires_at", table_name="worker_enrollments")
    op.drop_index("ix_worker_enrollments_job_type_id", table_name="worker_enrollments")
    op.drop_index("ix_worker_enrollments_owner_user_id", table_name="worker_enrollments")
    op.drop_table("worker_enrollments")
