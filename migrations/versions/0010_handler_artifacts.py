"""Add verifiable Job Type handler artifact reservations."""

from alembic import op
import sqlalchemy as sa

revision = "0010_handler_artifacts"
down_revision = "0009_producer_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "handler_artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_type_id", sa.String(length=36), nullable=False),
        sa.Column("object_ref", sa.Text(), nullable=False),
        sa.Column("expected_digest", sa.String(length=64), nullable=False),
        sa.Column("expected_size_bytes", sa.Integer(), nullable=False),
        sa.Column("actual_digest", sa.String(length=64), nullable=True),
        sa.Column("actual_size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "char_length(expected_digest) = 64",
            name="ck_handler_artifacts_expected_digest_length",
        ),
        sa.CheckConstraint(
            "expected_size_bytes > 0", name="ck_handler_artifacts_size"
        ),
        sa.ForeignKeyConstraint(
            ["job_type_id"], ["job_types.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("object_ref", name="uq_handler_artifacts_object_ref"),
    )
    op.create_index(
        "ix_handler_artifacts_job_type_id",
        "handler_artifacts",
        ["job_type_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_handler_artifacts_job_type_id", table_name="handler_artifacts"
    )
    op.drop_table("handler_artifacts")
