from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from distributed_job_queue.domain.job import InvalidJobTransition, JobStatus
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import Base, Worker
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
