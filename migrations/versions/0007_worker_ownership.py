"""Link registered worker agents to their owning user."""

from alembic import op
import sqlalchemy as sa

revision = "0007_worker_ownership"
down_revision = "0006_identity_and_job_ownership"
branch_labels = None
depends_on = None

BOOTSTRAP_USER_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.add_column(
        "workers", sa.Column("owner_user_id", sa.String(length=36), nullable=True)
    )
    op.execute(
        sa.text("UPDATE workers SET owner_user_id = :user_id").bindparams(
            user_id=BOOTSTRAP_USER_ID
        )
    )
    op.alter_column("workers", "owner_user_id", nullable=False)
    op.create_foreign_key(
        "fk_workers_owner_user_id_users",
        "workers",
        "users",
        ["owner_user_id"],
        ["id"],
    )
    op.create_index("ix_workers_owner_user_id", "workers", ["owner_user_id"])
    op.execute(
        sa.text(
            """
            INSERT INTO user_roles (user_id, role)
            VALUES (:user_id, 'WORKER')
            ON CONFLICT (user_id, role) DO NOTHING
            """
        ).bindparams(user_id=BOOTSTRAP_USER_ID)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM user_roles WHERE user_id = :user_id AND role = 'WORKER'"
        ).bindparams(user_id=BOOTSTRAP_USER_ID)
    )
    op.drop_index("ix_workers_owner_user_id", table_name="workers")
    op.drop_constraint(
        "fk_workers_owner_user_id_users", "workers", type_="foreignkey"
    )
    op.drop_column("workers", "owner_user_id")
