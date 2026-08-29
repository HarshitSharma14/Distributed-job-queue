"""Add Admin approval and signatures for handler releases."""

from alembic import op
import sqlalchemy as sa


revision = "0013_handler_release_approval"
down_revision = "0012_worker_agent_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_types",
        sa.Column("handler_signing_key_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "job_types",
        sa.Column("handler_release_signature", sa.Text(), nullable=True),
    )
    op.add_column(
        "handler_artifacts",
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "handler_artifacts",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "handler_artifacts",
        sa.Column("rejected_by_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "handler_artifacts",
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "handler_artifacts",
        sa.Column("signing_key_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "handler_artifacts",
        sa.Column("release_signature", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_handler_artifacts_approved_by_user",
        "handler_artifacts",
        "users",
        ["approved_by_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_handler_artifacts_rejected_by_user",
        "handler_artifacts",
        "users",
        ["rejected_by_user_id"],
        ["id"],
    )
    op.create_index(
        "ix_handler_artifacts_approved_by_user_id",
        "handler_artifacts",
        ["approved_by_user_id"],
    )
    op.create_index(
        "ix_handler_artifacts_rejected_by_user_id",
        "handler_artifacts",
        ["rejected_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_handler_artifacts_rejected_by_user_id",
        table_name="handler_artifacts",
    )
    op.drop_index(
        "ix_handler_artifacts_approved_by_user_id",
        table_name="handler_artifacts",
    )
    op.drop_constraint(
        "fk_handler_artifacts_approved_by_user",
        "handler_artifacts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_handler_artifacts_rejected_by_user",
        "handler_artifacts",
        type_="foreignkey",
    )
    op.drop_column("handler_artifacts", "release_signature")
    op.drop_column("handler_artifacts", "signing_key_id")
    op.drop_column("handler_artifacts", "approved_at")
    op.drop_column("handler_artifacts", "approved_by_user_id")
    op.drop_column("handler_artifacts", "rejected_at")
    op.drop_column("handler_artifacts", "rejected_by_user_id")
    op.drop_column("job_types", "handler_release_signature")
    op.drop_column("job_types", "handler_signing_key_id")
