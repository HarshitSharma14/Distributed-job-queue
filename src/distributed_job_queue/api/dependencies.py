"""FastAPI dependencies shared by API routes."""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from distributed_job_queue.persistence.database import SessionFactory


def get_session() -> Iterator[Session]:
    """Provide one transaction that commits only after the request succeeds."""

    with SessionFactory.begin() as session:
        yield session
