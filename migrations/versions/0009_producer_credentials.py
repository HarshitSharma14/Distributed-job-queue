"""Add scoped and revocable Producer API credentials."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_producer_credentials"
down_revision = "0008_browser_authentication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "producer_credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_prefix", sa.String(length=20), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("key_hash", name="uq_producer_credentials_key_hash"),
    )
    op.create_index(
        "ix_producer_credentials_user_id", "producer_credentials", ["user_id"]
    )
    op.create_index(
        "ix_producer_credentials_expires_at",
        "producer_credentials",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_producer_credentials_expires_at", table_name="producer_credentials"
    )
    op.drop_index(
        "ix_producer_credentials_user_id", table_name="producer_credentials"
    )
    op.drop_table("producer_credentials")
