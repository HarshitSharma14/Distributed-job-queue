from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.domain.worker import WorkerStatus
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import JobAttempt, OutboxEvent, Worker
from distributed_job_queue.persistence.repositories import JobRepository
from distributed_job_queue.recovery.service import recover_stale_work


@pytest.fixture
def recovery_context():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_recovery_fences_expired_attempt_and_schedules_retry(recovery_context):
    session = recovery_context
    now = datetime.now(timezone.utc)
    worker = Worker(
        id=f"crashed-worker-{uuid4()}",
        capabilities=["reports"],
        status=WorkerStatus.ONLINE.value,
        last_heartbeat_at=now - timedelta(minutes=2),
    )
    session.add(worker)
    session.flush()

    repository = JobRepository(session)
    job = repository.create(
        job_type="generate_report",
        queue="reports",
        payload={"report_id": 42},
    )
    repository.transition(job, JobStatus.QUEUED)
    repository.mark_running(
        job.id,
        worker_id=worker.id,
        lease_token=str(uuid4()),
        lease_expires_at=now - timedelta(seconds=1),
    )

    result = recover_stale_work(
        session,
        now=now,
        worker_offline_after_seconds=60,
        retry_base_delay_seconds=5,
        retry_max_delay_seconds=300,
        limit=100,
    )

    assert result.offline_worker_ids == [worker.id]
    assert result.recovered_job_ids == [job.id]
    assert worker.status == WorkerStatus.OFFLINE.value
    assert job.status == JobStatus.RETRY_WAIT.value
    assert now + timedelta(seconds=5) <= job.available_at <= now + timedelta(seconds=10)
    assert job.worker_id is None
    assert job.lease_token is None
    assert job.lease_expires_at is None

    attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == job.id))
    assert attempt is not None
    assert attempt.status == JobStatus.FAILED.value
    assert attempt.finished_at == now
    assert attempt.error == {
        "type": "LeaseExpired",
        "message": "Worker lease expired",
    }
    outbox_count = session.scalar(
        select(func.count()).select_from(OutboxEvent).where(OutboxEvent.job_id == job.id)
    )
    assert outbox_count == 1
