import uuid

import pytest
from redis import Redis
from sqlalchemy import delete, select

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.models import Job, Worker
from distributed_job_queue.persistence.repositories import JobRepository
from distributed_job_queue.queueing import RedisQueue
from distributed_job_queue.workers import HandlerRegistry, UnknownJobHandler, WorkerConsumer


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


def create_queued_job(queue_name: str) -> str:
    with SessionFactory.begin() as session:
        repository = JobRepository(session)
        job = repository.create(
            job_type="generate_report",
            queue=queue_name,
            payload={"report_id": 42},
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
