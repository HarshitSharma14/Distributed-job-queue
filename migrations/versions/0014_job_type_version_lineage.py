"""Add immutable Job Type version lineage."""

from alembic import op
import sqlalchemy as sa


revision = "0014_job_type_version_lineage"
down_revision = "0013_handler_release_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_types",
        sa.Column("supersedes_job_type_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_job_types_supersedes_job_type",
        "job_types",
        "job_types",
        ["supersedes_job_type_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_job_types_supersedes_job_type_id",
        "job_types",
        ["supersedes_job_type_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_job_types_supersedes_job_type_id",
        "job_types",
        type_="unique",
    )
    op.drop_constraint(
        "fk_job_types_supersedes_job_type",
        "job_types",
        type_="foreignkey",
    )
    op.drop_column("job_types", "supersedes_job_type_id")
