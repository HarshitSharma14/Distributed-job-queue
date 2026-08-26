import pytest
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import OutboxEvent
from distributed_job_queue.persistence.repositories import JobRepository
from distributed_job_queue.publisher import OutboxPublisher
from distributed_job_queue.queueing import RedisQueue


@pytest.fixture
def publisher_context():
    client = Redis.from_url(load_settings().redis_url, decode_responses=True)
    queue_name = "publisher-integration-test"
    redis_keys = [
        f"job-queue:{queue_name}",
        f"job-queue-sequence:{queue_name}",
    ]
    client.delete(*redis_keys)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session, OutboxPublisher(RedisQueue(client)), client, queue_name
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        client.delete(*redis_keys)


def test_publisher_enqueues_job_and_marks_event_published(publisher_context):
    session, publisher, client, queue_name = publisher_context
    job = JobRepository(session).create(
        job_type="generate_report",
        queue=queue_name,
        payload={},
        priority=5,
    )

    assert publisher.publish_batch(session) == 1

    event = session.scalar(select(OutboxEvent).where(OutboxEvent.job_id == job.id))
    assert job.status == JobStatus.QUEUED.value
    assert event is not None and event.published_at is not None
    assert client.zcard(f"job-queue:{queue_name}") == 1


def test_publisher_retry_is_idempotent_after_database_rollback(publisher_context):
    session, publisher, client, queue_name = publisher_context
    job = JobRepository(session).create(
        job_type="generate_report",
        queue=queue_name,
        payload={},
        priority=5,
    )
    savepoint = session.begin_nested()
    assert publisher.publish_batch(session) == 1
    savepoint.rollback()
    session.expire_all()

    assert publisher.publish_batch(session) == 1

    event = session.scalar(select(OutboxEvent).where(OutboxEvent.job_id == job.id))
    assert client.zcard(f"job-queue:{queue_name}") == 1
    assert event is not None and event.published_at is not None
