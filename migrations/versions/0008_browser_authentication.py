"""Add password credentials and revocable browser sessions."""

from alembic import op
import sqlalchemy as sa

revision = "0008_browser_authentication"
down_revision = "0007_worker_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.create_table(
        "browser_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_browser_sessions_token_hash"),
    )
    op.create_index(
        "ix_browser_sessions_user_id", "browser_sessions", ["user_id"]
    )
    op.create_index(
        "ix_browser_sessions_expires_at", "browser_sessions", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_browser_sessions_expires_at", table_name="browser_sessions")
    op.drop_index("ix_browser_sessions_user_id", table_name="browser_sessions")
    op.drop_table("browser_sessions")
    op.drop_column("users", "password_hash")
