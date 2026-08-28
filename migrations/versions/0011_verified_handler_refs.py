"""Store the promoted immutable reference for verified handlers."""

from alembic import op
import sqlalchemy as sa

revision = "0011_verified_handler_refs"
down_revision = "0010_handler_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "handler_artifacts", sa.Column("verified_ref", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("handler_artifacts", "verified_ref")
