"""Add users, job types, roles, and immutable job ownership."""

from alembic import op
import sqlalchemy as sa

revision = "0006_identity_and_job_ownership"
down_revision = "0005_dead_lettered_at"
branch_labels = None
depends_on = None

BOOTSTRAP_USER_ID = "00000000-0000-0000-0000-000000000001"
BOOTSTRAP_JOB_TYPE_ID = "00000000-0000-0000-0000-000000000002"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role"),
    )
    op.create_table(
        "job_types",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("publisher_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("queue", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("handler_ref", sa.Text(), nullable=True),
        sa.Column("handler_digest", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["publisher_id"], ["users.id"]),
        sa.UniqueConstraint(
            "publisher_id",
            "name",
            "version",
            name="uq_job_types_publisher_name_version",
        ),
        sa.UniqueConstraint("id", "publisher_id", name="uq_job_types_id_publisher"),
    )
    op.create_index("ix_job_types_publisher_id", "job_types", ["publisher_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO users (id, email, display_name, status)
            VALUES (:user_id, 'bootstrap@local.invalid', 'Bootstrap System', 'ACTIVE')
            """
        ).bindparams(user_id=BOOTSTRAP_USER_ID)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO user_roles (user_id, role)
            VALUES (:user_id, 'ADMIN'), (:user_id, 'PUBLISHER'), (:user_id, 'PRODUCER')
            """
        ).bindparams(user_id=BOOTSTRAP_USER_ID)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO job_types (
                id, publisher_id, name, version, queue, status
            ) VALUES (
                :job_type_id, :user_id, '__legacy_dynamic__', 1, '*', 'ACTIVE'
            )
            """
        ).bindparams(
            job_type_id=BOOTSTRAP_JOB_TYPE_ID,
            user_id=BOOTSTRAP_USER_ID,
        )
    )

    op.add_column("jobs", sa.Column("job_type_id", sa.String(length=36), nullable=True))
    op.add_column("jobs", sa.Column("publisher_id", sa.String(length=36), nullable=True))
    op.add_column("jobs", sa.Column("producer_id", sa.String(length=36), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE jobs
            SET job_type_id = :job_type_id,
                publisher_id = :user_id,
                producer_id = :user_id
            """
        ).bindparams(
            job_type_id=BOOTSTRAP_JOB_TYPE_ID,
            user_id=BOOTSTRAP_USER_ID,
        )
    )
    op.alter_column("jobs", "job_type_id", nullable=False)
    op.alter_column("jobs", "publisher_id", nullable=False)
    op.alter_column("jobs", "producer_id", nullable=False)
    op.create_foreign_key(
        "fk_jobs_job_type_publisher",
        "jobs",
        "job_types",
        ["job_type_id", "publisher_id"],
        ["id", "publisher_id"],
    )
    op.create_foreign_key(
        "fk_jobs_producer_id_users", "jobs", "users", ["producer_id"], ["id"]
    )
    op.create_index("ix_jobs_job_type_id", "jobs", ["job_type_id"])
    op.create_index("ix_jobs_publisher_id", "jobs", ["publisher_id"])
    op.create_index("ix_jobs_producer_id", "jobs", ["producer_id"])

    op.drop_constraint("uq_jobs_idempotency_key", "jobs", type_="unique")
    op.create_unique_constraint(
        "uq_jobs_producer_idempotency_key",
        "jobs",
        ["producer_id", "idempotency_key"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_job_ownership_change()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.job_type_id IS DISTINCT FROM OLD.job_type_id
               OR NEW.publisher_id IS DISTINCT FROM OLD.publisher_id
               OR NEW.producer_id IS DISTINCT FROM OLD.producer_id THEN
                RAISE EXCEPTION 'job ownership is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_jobs_immutable_ownership
        BEFORE UPDATE ON jobs
        FOR EACH ROW EXECUTE FUNCTION prevent_job_ownership_change()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_jobs_immutable_ownership ON jobs")
    op.execute("DROP FUNCTION prevent_job_ownership_change()")
    op.drop_constraint("uq_jobs_producer_idempotency_key", "jobs", type_="unique")
    op.create_unique_constraint("uq_jobs_idempotency_key", "jobs", ["idempotency_key"])
    op.drop_index("ix_jobs_producer_id", table_name="jobs")
    op.drop_index("ix_jobs_publisher_id", table_name="jobs")
    op.drop_index("ix_jobs_job_type_id", table_name="jobs")
    op.drop_constraint("fk_jobs_producer_id_users", "jobs", type_="foreignkey")
    op.drop_constraint("fk_jobs_job_type_publisher", "jobs", type_="foreignkey")
    op.drop_column("jobs", "producer_id")
    op.drop_column("jobs", "publisher_id")
    op.drop_column("jobs", "job_type_id")
    op.drop_index("ix_job_types_publisher_id", table_name="job_types")
    op.drop_table("job_types")
    op.drop_table("user_roles")
    op.drop_table("users")
