from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from distributed_job_queue.domain.job import InvalidJobTransition, JobStatus
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import OutboxEvent, Worker
from distributed_job_queue.persistence.repositories.jobs import JobRepository


@pytest.fixture
def repository():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield JobRepository(session), session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_create_read_and_transition_job(repository):
    job_repository, session = repository

    job = job_repository.create(
        job_type="generate_report",
        queue="default",
        payload={"user_id": 123},
        priority=5,
    )
    assert job.status == JobStatus.CREATED.value
    assert job.attempts == 0
    outbox_count = session.scalar(select(func.count()).select_from(OutboxEvent))
    assert outbox_count == 1

    job_repository.transition(job, JobStatus.QUEUED)
    job_repository.transition(job, JobStatus.RUNNING)
    session.flush()

    stored_job = job_repository.get(job.id)
    assert stored_job is not None
    assert stored_job.status == JobStatus.RUNNING.value
    assert stored_job.payload == {"user_id": 123}


def test_invalid_transition_and_attempt_history(repository):
    job_repository, session = repository
    worker = Worker(id="integration-worker", capabilities=["reports"])
    session.add(worker)
    session.flush()

    job = job_repository.create(
        job_type="generate_report",
        queue="default",
        payload={},
    )

    with pytest.raises(InvalidJobTransition):
        job_repository.transition(job, JobStatus.COMPLETED)

    job_repository.transition(job, JobStatus.QUEUED)
    job_repository.transition(job, JobStatus.RUNNING)
    attempt = job_repository.record_attempt(
        job,
        worker_id=worker.id,
        status="FAILED",
        error={"message": "temporary failure"},
        finished_at=datetime.now(timezone.utc),
    )
    job_repository.set_error(job, {"message": "temporary failure"})
    session.flush()

    assert attempt.attempt_number == 1
    assert job.attempts == 1
    assert job.error == {"message": "temporary failure"}


def test_claim_and_recover_expired_job_from_postgres(repository):
    job_repository, session = repository
    worker = Worker(id="recovery-worker", capabilities=["reports"])
    session.add(worker)
    job = job_repository.create(
        job_type="generate_report",
        queue="reports",
        payload={},
        priority=4,
    )
    job_repository.transition(job, JobStatus.QUEUED)
    expired_at = datetime.now(timezone.utc)
    job_repository.mark_running(
        job.id,
        worker_id=worker.id,
        lease_token="lease-token",
        lease_expires_at=expired_at,
    )

    recovered = job_repository.recover_expired(now=expired_at, limit=10)

    assert [item.id for item in recovered] == [job.id]
    assert job.status == JobStatus.QUEUED.value
    assert job.worker_id is None
    assert job.lease_token is None
    assert job.lease_expires_at is None
    outbox_count = session.scalar(select(func.count()).select_from(OutboxEvent))
    assert outbox_count == 2


def test_reconcile_queued_job_creates_missing_outbox_event(repository):
    job_repository, session = repository
    job = job_repository.create(
        job_type="generate_report",
        queue="reports",
        payload={},
    )
    job_repository.transition(job, JobStatus.QUEUED)
    events = list(session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job.id)))
    events[0].published_at = datetime.now(timezone.utc)
    session.flush()

    reconciled = job_repository.reconcile_queued()

    assert [item.id for item in reconciled] == [job.id]
    pending_count = session.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(OutboxEvent.job_id == job.id, OutboxEvent.published_at.is_(None))
    )
    assert pending_count == 1
