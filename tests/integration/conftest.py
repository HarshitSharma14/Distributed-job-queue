"""Create a clean, migrated PostgreSQL database for integration tests."""

import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from distributed_job_queue.common.config import load_settings


def _prepare_test_database() -> None:
    database_url = load_settings().database_url
    parsed = make_url(database_url)
    database_name = parsed.database or ""
    if not re.fullmatch(r"[A-Za-z0-9_]+_test", database_name):
        raise RuntimeError(
            "TEST_DATABASE_URL must target a dedicated database ending in '_test'"
        )
    admin_url = parsed.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        admin_engine.dispose()

    repository_root = Path(__file__).resolve().parents[2]
    configuration = Config(str(repository_root / "alembic.ini"))
    configuration.set_main_option(
        "script_location", str(repository_root / "migrations")
    )
    configuration.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(configuration, "head")


_prepare_test_database()
