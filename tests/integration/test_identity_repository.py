from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import Job, Worker
from distributed_job_queue.persistence.repositories import IdentityRepository, JobRepository


@pytest.fixture
def repositories():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield IdentityRepository(session), JobRepository(session), session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_user_roles_job_type_and_job_ownership_are_persisted(repositories):
    identities, jobs, _ = repositories
    publisher = identities.create_user(
        email=f"publisher-{uuid4()}@example.com",
        display_name="Report Publisher",
    )
    producer = identities.create_user(
        email=f"producer-{uuid4()}@example.com",
        display_name="Report Producer",
    )
    identities.assign_role(publisher, UserRole.PUBLISHER)
    identities.assign_role(producer, UserRole.PRODUCER)
    identities.assign_role(producer, UserRole.WORKER)
    job_type = identities.create_job_type(
        publisher_id=publisher.id,
        name="generate_report",
        version=1,
        queue="reports",
        handler_ref="handlers/generate-report/1.zip",
        handler_digest="a" * 64,
    )

    job = jobs.create(
        job_type="generate_report",
        job_type_id=job_type.id,
        publisher_id=publisher.id,
        producer_id=producer.id,
        queue=job_type.queue,
        payload={"report_id": 42},
    )
    worker = Worker(
        id=f"worker-{uuid4()}",
        owner_user_id=producer.id,
        capabilities=["generate_report"],
    )
    jobs.session.add(worker)
    jobs.session.flush()

    stored_publisher = identities.get_user_with_roles(publisher.id)
    assert stored_publisher is not None
    assert {assignment.role for assignment in stored_publisher.roles} == {
        UserRole.PUBLISHER.value
    }
    assert job.job_type_id == job_type.id
    assert job.publisher_id == publisher.id
    assert job.producer_id == producer.id
    assert worker.owner_user_id == producer.id


def test_idempotency_keys_are_scoped_to_the_producer(repositories):
    identities, jobs, _ = repositories
    publisher = identities.create_user(
        email=f"publisher-{uuid4()}@example.com", display_name="Publisher"
    )
    first_producer = identities.create_user(
        email=f"producer-a-{uuid4()}@example.com", display_name="Producer A"
    )
    second_producer = identities.create_user(
        email=f"producer-b-{uuid4()}@example.com", display_name="Producer B"
    )
    job_type = identities.create_job_type(
        publisher_id=publisher.id,
        name="send_email",
        queue="emails",
    )

    first = jobs.create(
        job_type="send_email",
        job_type_id=job_type.id,
        publisher_id=publisher.id,
        producer_id=first_producer.id,
        queue="emails",
        payload={},
        idempotency_key="request-1",
        request_hash="a" * 64,
    )
    second = jobs.create(
        job_type="send_email",
        job_type_id=job_type.id,
        publisher_id=publisher.id,
        producer_id=second_producer.id,
        queue="emails",
        payload={},
        idempotency_key="request-1",
        request_hash="a" * 64,
    )

    assert first.id != second.id
    assert jobs.get_by_idempotency_key(
        "request-1", producer_id=first_producer.id
    ) == first
    assert jobs.get_by_idempotency_key(
        "request-1", producer_id=second_producer.id
    ) == second


def test_job_type_must_belong_to_the_recorded_publisher(repositories):
    identities, jobs, session = repositories
    owner = identities.create_user(
        email=f"owner-{uuid4()}@example.com", display_name="Owner"
    )
    other_publisher = identities.create_user(
        email=f"other-{uuid4()}@example.com", display_name="Other"
    )
    producer = identities.create_user(
        email=f"producer-{uuid4()}@example.com", display_name="Producer"
    )
    job_type = identities.create_job_type(
        publisher_id=owner.id,
        name="generate_report",
        queue="reports",
    )

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            jobs.create(
                job_type="generate_report",
                job_type_id=job_type.id,
                publisher_id=other_publisher.id,
                producer_id=producer.id,
                queue="reports",
                payload={},
            )


def test_job_ownership_cannot_change_after_submission(repositories):
    identities, jobs, session = repositories
    publisher = identities.create_user(
        email=f"publisher-{uuid4()}@example.com", display_name="Publisher"
    )
    producer = identities.create_user(
        email=f"producer-{uuid4()}@example.com", display_name="Producer"
    )
    replacement = identities.create_user(
        email=f"replacement-{uuid4()}@example.com", display_name="Replacement"
    )
    job_type = identities.create_job_type(
        publisher_id=publisher.id,
        name="generate_report",
        queue="reports",
    )
    job = jobs.create(
        job_type="generate_report",
        job_type_id=job_type.id,
        publisher_id=publisher.id,
        producer_id=producer.id,
        queue="reports",
        payload={},
    )

    with pytest.raises(DBAPIError, match="job ownership is immutable"):
        with session.begin_nested():
            session.execute(
                update(Job).where(Job.id == job.id).values(producer_id=replacement.id)
            )
