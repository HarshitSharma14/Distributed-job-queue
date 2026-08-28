from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.database import SessionFactory, engine
from distributed_job_queue.persistence.models import Job, OutboxEvent, Worker
from distributed_job_queue.persistence.repositories import JobRepository
from distributed_job_queue.publisher.service import OutboxPublisher
from distributed_job_queue.scheduler.service import release_due_retries


class RecordingQueue:
    def __init__(self) -> None:
        self.enqueued = []

    def enqueue(self, job_id, *, queue, priority):
        self.enqueued.append((job_id, queue, priority))
        return True


@pytest.fixture
def scheduler_context():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    worker = Worker(id=f"scheduler-worker-{uuid4()}", capabilities=["reports"])
    session.add(worker)
    session.flush()
    try:
        yield session, worker
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def create_retry_job(
    session: Session,
    worker: Worker,
    *,
    available_at: datetime,
    queue_name: str,
) -> Job:
    repository = JobRepository(session)
    job = repository.create(
        job_type="generate_report",
        queue=queue_name,
        payload={"report_id": 42},
        priority=7,
    )
    repository.transition(job, JobStatus.QUEUED)
    now = datetime.now(timezone.utc)
    lease_token = str(uuid4())
    repository.mark_running(
        job.id,
        worker_id=worker.id,
        lease_token=lease_token,
        lease_expires_at=now + timedelta(minutes=1),
    )
    repository.fail_execution(
        job.id,
        worker_id=worker.id,
        lease_token=lease_token,
        error={"type": "RuntimeError", "message": "temporary failure"},
        now=now,
        retry_at=available_at,
    )
    for event in session.scalars(
        select(OutboxEvent).where(OutboxEvent.job_id == job.id)
    ):
        event.published_at = now
    session.flush()
    return job


def test_scheduler_releases_only_due_retries_through_outbox(scheduler_context):
    session, worker = scheduler_context
    now = datetime.now(timezone.utc)
    queue_name = f"retry-{uuid4()}"
    due = create_retry_job(
        session,
        worker,
        available_at=now - timedelta(seconds=1),
        queue_name=queue_name,
    )
    future = create_retry_job(
        session,
        worker,
        available_at=now + timedelta(minutes=5),
        queue_name=queue_name,
    )

    released = release_due_retries(session, now=now, limit=100)

    assert released == [due.id]
    assert due.status == JobStatus.QUEUED.value
    assert future.status == JobStatus.RETRY_WAIT.value
    pending = list(
        session.scalars(
            select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
        )
    )
    assert len(pending) == 1
    assert pending[0].job_id == due.id
    assert pending[0].payload == {
        "job_id": due.id,
        "queue": queue_name,
        "priority": 7,
    }


def test_scheduler_batch_can_be_published_idempotently(scheduler_context):
    session, worker = scheduler_context
    now = datetime.now(timezone.utc)
    queue_name = f"retry-publish-{uuid4()}"
    due = create_retry_job(
        session,
        worker,
        available_at=now - timedelta(seconds=1),
        queue_name=queue_name,
    )
    queue = RecordingQueue()

    assert release_due_retries(session, now=now, limit=1) == [due.id]
    assert OutboxPublisher(queue).publish_batch(session, limit=10) == 1
    assert OutboxPublisher(queue).publish_batch(session, limit=10) == 0

    assert queue.enqueued == [(due.id, queue_name, 7)]
    assert due.status == JobStatus.QUEUED.value


def test_concurrent_schedulers_do_not_release_the_same_retry():
    suffix = uuid4().hex
    worker_id = f"concurrent-scheduler-worker-{suffix}"
    queue_name = f"concurrent-retry-{suffix}"
    now = datetime.now(timezone.utc)
    with SessionFactory.begin() as setup:
        worker = Worker(id=worker_id, capabilities=["reports"])
        setup.add(worker)
        setup.flush()
        job = create_retry_job(
            setup,
            worker,
            available_at=now - timedelta(seconds=1),
            queue_name=queue_name,
        )
        job_id = job.id

    first = SessionFactory()
    second = SessionFactory()
    first_transaction = first.begin()
    second_transaction = second.begin()
    try:
        first_release = release_due_retries(first, now=now, limit=1)
        second_release = release_due_retries(second, now=now, limit=1)

        assert first_release == [job_id]
        assert second_release == []
        first_transaction.commit()
        second_transaction.commit()
    finally:
        if first_transaction.is_active:
            first_transaction.rollback()
        if second_transaction.is_active:
            second_transaction.rollback()
        first.close()
        second.close()
        with SessionFactory.begin() as cleanup:
            cleanup.execute(delete(Job).where(Job.id == job_id))
            cleanup.execute(delete(Worker).where(Worker.id == worker_id))
