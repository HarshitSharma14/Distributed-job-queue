import threading
import time
from uuid import uuid4

from sqlalchemy import delete, select

from distributed_job_queue.api.job_type_services import (
    JobTypeStateConflict,
    create_next_job_type_version,
)
from distributed_job_queue.domain.identity import JobTypeStatus
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.models import JobType, User
from distributed_job_queue.persistence.repositories import IdentityRepository


def test_concurrent_version_creation_preserves_one_linear_successor():
    with SessionFactory.begin() as setup:
        identities = IdentityRepository(setup)
        publisher = identities.create_user(
            email=f"version-race-{uuid4()}@example.com",
            display_name="Version Race Publisher",
        )
        source = identities.create_job_type(
            publisher_id=publisher.id,
            name=f"version_race_{uuid4().hex}",
            queue="reports",
            status=JobTypeStatus.ACTIVE,
        )
        publisher_id = publisher.id
        source_id = source.id

    first_session = SessionFactory()
    first_transaction = first_session.begin()
    first = create_next_job_type_version(
        first_session,
        source_id,
        publisher_id=publisher_id,
        queue=None,
    )
    second_errors: list[Exception] = []

    def create_concurrently() -> None:
        try:
            with SessionFactory.begin() as session:
                create_next_job_type_version(
                    session,
                    source_id,
                    publisher_id=publisher_id,
                    queue=None,
                )
        except Exception as exc:
            second_errors.append(exc)

    thread = threading.Thread(target=create_concurrently, daemon=True)
    thread.start()
    time.sleep(0.1)
    first_transaction.commit()
    thread.join(timeout=5)

    try:
        assert thread.is_alive() is False
        assert first is not None
        assert len(second_errors) == 1
        assert isinstance(second_errors[0], JobTypeStateConflict)
        with SessionFactory() as session:
            versions = list(
                session.scalars(
                    select(JobType)
                    .where(JobType.publisher_id == publisher_id)
                    .order_by(JobType.version)
                )
            )
            assert [job_type.version for job_type in versions] == [1, 2]
            assert versions[1].supersedes_job_type_id == versions[0].id
    finally:
        first_session.close()
        with SessionFactory.begin() as cleanup:
            cleanup.execute(
                delete(JobType).where(JobType.publisher_id == publisher_id)
            )
            cleanup.execute(delete(User).where(User.id == publisher_id))
