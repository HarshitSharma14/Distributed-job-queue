import threading
import time
import uuid

import pytest
from redis import Redis
from sqlalchemy import delete, select

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.models import Job, JobAttempt, Worker
from distributed_job_queue.persistence.repositories import JobRepository
from distributed_job_queue.queueing import RedisQueue
from distributed_job_queue.workers import (
    HandlerRegistry,
    LeaseLost,
    UnknownJobHandler,
    WorkerConsumer,
    WorkerExecutor,
)
from distributed_job_queue.workers.runner import consume_loop


@pytest.fixture
def consumer_context():
    suffix = uuid.uuid4().hex
    queue_name = f"consumer-test-{suffix}"
    worker_id = f"worker-{suffix}"
    client = Redis.from_url(load_settings().redis_url, decode_responses=True)
    queue = RedisQueue(client)
    registry = HandlerRegistry()

    with SessionFactory.begin() as session:
        session.add(Worker(id=worker_id, capabilities=[queue_name]))

    try:
        yield queue, registry, client, queue_name, worker_id
    finally:
        with SessionFactory.begin() as session:
            job_ids = list(
                session.scalars(select(Job.id).where(Job.queue == queue_name))
            )
            session.execute(delete(Job).where(Job.queue == queue_name))
            session.execute(delete(Worker).where(Worker.id == worker_id))
        keys = [
            f"job-queue:{queue_name}",
            f"job-queue-sequence:{queue_name}",
            f"job-inflight:{queue_name}",
            f"job-inflight-score:{queue_name}",
            f"job-notification:{queue_name}",
            *(f"job-lease:{job_id}" for job_id in job_ids),
        ]
        client.delete(*keys)


def create_queued_job(queue_name: str, *, max_attempts: int = 5) -> str:
    with SessionFactory.begin() as session:
        repository = JobRepository(session)
        job = repository.create(
            job_type="generate_report",
            queue=queue_name,
            payload={"report_id": 42},
            max_attempts=max_attempts,
        )
        repository.transition(job, JobStatus.QUEUED)
        return job.id


def test_consumer_claims_job_and_persists_ownership(consumer_context):
    queue, registry, _, queue_name, worker_id = consumer_context
    registry.register("generate_report", lambda payload: payload["report_id"])
    job_id = create_queued_job(queue_name)
    queue.enqueue(job_id, queue=queue_name)

    claimed = WorkerConsumer(queue, registry).claim_next(
        queue_name,
        worker_id=worker_id,
        lease_seconds=60,
        wait_seconds=0,
    )

    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.payload == {"report_id": 42}
    assert claimed.handler(claimed.payload) == 42
    with SessionFactory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.RUNNING.value
        assert job.worker_id == worker_id
        assert job.lease_token == claimed.lease.token


def test_unknown_handler_returns_job_to_ready(consumer_context):
    queue, registry, _, queue_name, worker_id = consumer_context
    job_id = create_queued_job(queue_name)
    queue.enqueue(job_id, queue=queue_name)

    with pytest.raises(UnknownJobHandler, match="generate_report"):
        WorkerConsumer(queue, registry).claim_next(
            queue_name,
            worker_id=worker_id,
            lease_seconds=60,
            wait_seconds=0,
        )

    assert queue.queue_size(queue_name) == 1
    with SessionFactory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.QUEUED.value


def test_executor_renews_lease_and_completes_slow_handler(consumer_context):
    queue, registry, _, queue_name, worker_id = consumer_context

    def slow_handler(payload):
        time.sleep(1.2)
        return payload["report_id"]

    registry.register("generate_report", slow_handler)
    job_id = create_queued_job(queue_name)
    queue.enqueue(job_id, queue=queue_name)
    claimed = WorkerConsumer(queue, registry).claim_next(
        queue_name,
        worker_id=worker_id,
        lease_seconds=1,
        wait_seconds=0,
    )
    assert claimed is not None

    outcome = WorkerExecutor(
        queue,
        lease_seconds=1,
        renewal_interval_seconds=0.2,
    ).execute(claimed)

    assert outcome.status == JobStatus.COMPLETED
    assert outcome.result == 42
    assert outcome.lease_released is True
    assert queue.inflight_size(queue_name) == 0
    with SessionFactory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED.value
        assert job.attempts == 1
        assert job.worker_id is None
        attempts = list(
            session.scalars(
                select(JobAttempt).where(JobAttempt.job_id == job_id)
            )
        )
        assert [attempt.status for attempt in attempts] == [
            JobStatus.COMPLETED.value
        ]


def test_executor_records_handler_failure(consumer_context):
    queue, registry, _, queue_name, worker_id = consumer_context

    def failing_handler(_payload):
        raise RuntimeError("report service unavailable")

    registry.register("generate_report", failing_handler)
    job_id = create_queued_job(queue_name)
    queue.enqueue(job_id, queue=queue_name)
    claimed = WorkerConsumer(queue, registry).claim_next(
        queue_name,
        worker_id=worker_id,
        lease_seconds=10,
        wait_seconds=0,
    )
    assert claimed is not None

    outcome = WorkerExecutor(queue, lease_seconds=10).execute(claimed)

    assert outcome.status == JobStatus.RETRY_WAIT
    assert outcome.error == {
        "type": "RuntimeError",
        "message": "report service unavailable",
    }
    assert outcome.lease_released is True
    with SessionFactory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.RETRY_WAIT.value
        assert job.attempts == 1
        assert job.error == outcome.error
        attempt = session.scalar(
            select(JobAttempt).where(JobAttempt.job_id == job_id)
        )
        assert attempt is not None
        assert attempt.status == JobStatus.FAILED.value


def test_executor_rejects_completion_after_redis_lease_is_lost(consumer_context):
    queue, registry, client, queue_name, worker_id = consumer_context

    def handler_after_lease_loss(payload):
        time.sleep(0.3)
        return payload["report_id"]

    registry.register("generate_report", handler_after_lease_loss)
    job_id = create_queued_job(queue_name)
    queue.enqueue(job_id, queue=queue_name)
    claimed = WorkerConsumer(queue, registry).claim_next(
        queue_name,
        worker_id=worker_id,
        lease_seconds=1,
        wait_seconds=0,
    )
    assert claimed is not None
    client.delete(f"job-lease:{job_id}")

    with pytest.raises(LeaseLost, match=job_id):
        WorkerExecutor(
            queue,
            lease_seconds=1,
            renewal_interval_seconds=0.1,
        ).execute(claimed)

    with SessionFactory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.RUNNING.value
        assert job.attempts == 1
        attempt = session.scalar(
            select(JobAttempt).where(JobAttempt.job_id == job_id)
        )
        assert attempt is not None
        assert attempt.status == JobStatus.RUNNING.value


def test_executor_marks_job_failed_when_attempts_are_exhausted(consumer_context):
    queue, registry, _, queue_name, worker_id = consumer_context

    def failing_handler(_payload):
        raise ValueError("invalid report")

    registry.register("generate_report", failing_handler)
    job_id = create_queued_job(queue_name, max_attempts=1)
    queue.enqueue(job_id, queue=queue_name)
    claimed = WorkerConsumer(queue, registry).claim_next(
        queue_name,
        worker_id=worker_id,
        lease_seconds=10,
        wait_seconds=0,
    )
    assert claimed is not None

    outcome = WorkerExecutor(queue, lease_seconds=10).execute(claimed)

    assert outcome.status == JobStatus.FAILED
    with SessionFactory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED.value
        assert job.attempts == 1


def test_worker_loop_claims_and_executes_job_end_to_end(consumer_context):
    queue, registry, _, queue_name, worker_id = consumer_context
    registry.register("generate_report", lambda payload: payload["report_id"])
    job_id = create_queued_job(queue_name)
    queue.enqueue(job_id, queue=queue_name)
    consumer = WorkerConsumer(queue, registry)
    executor = WorkerExecutor(queue, lease_seconds=10)
    stop = threading.Event()

    class StopAfterExecution:
        def execute(self, claimed):
            outcome = executor.execute(claimed)
            stop.set()
            return outcome

    consume_loop(
        stop,
        worker_id=worker_id,
        queue_names=[queue_name],
        consumer=consumer,
        executor=StopAfterExecution(),
        lease_seconds=10,
        wait_seconds=0,
    )

    with SessionFactory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED.value
        assert job.attempts == 1
