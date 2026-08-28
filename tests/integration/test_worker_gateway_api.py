import asyncio
from datetime import datetime
from uuid import uuid4

import httpx
import pytest
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from distributed_job_queue.api.app import app
from distributed_job_queue.api.dependencies import (
    get_redis_queue,
    get_session,
    get_session_factory,
)
from distributed_job_queue.common.config import load_settings
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.domain.worker import WorkerStatus
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import Job, JobAttempt, Worker
from distributed_job_queue.persistence.repositories import JobRepository
from distributed_job_queue.queueing import RedisQueue

WORKER_TOKEN = "integration-worker-token"


@pytest.fixture
def gateway_context(monkeypatch):
    monkeypatch.setenv("WORKER_GATEWAY_TOKEN", WORKER_TOKEN)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield session
    finally:
        app.dependency_overrides.clear()
        session.close()
        transaction.rollback()
        connection.close()


def gateway_request(
    method: str,
    path: str,
    *,
    request_body: dict | None = None,
    token: str | None = WORKER_TOKEN,
) -> httpx.Response:
    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {token}"} if token else None
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(
                method, path, json=request_body, headers=headers
            )

    return asyncio.run(send_request())


@pytest.fixture
def claim_gateway_context(monkeypatch):
    monkeypatch.setenv("WORKER_GATEWAY_TOKEN", WORKER_TOKEN)
    suffix = uuid4().hex
    queue_name = f"gateway-claim-{suffix}"
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    request_session_factory = sessionmaker(
        bind=connection,
        class_=Session,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    redis_client = Redis.from_url(
        load_settings().redis_url, decode_responses=True
    )
    queue = RedisQueue(redis_client)

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_session_factory] = lambda: request_session_factory
    app.dependency_overrides[get_redis_queue] = lambda: queue
    try:
        yield session, queue, redis_client, queue_name
    finally:
        job_ids = list(
            session.scalars(select(Job.id).where(Job.queue == queue_name))
        )
        app.dependency_overrides.clear()
        redis_client.delete(
            f"job-queue:{queue_name}",
            f"job-queue-sequence:{queue_name}",
            f"job-inflight:{queue_name}",
            f"job-inflight-score:{queue_name}",
            f"job-notification:{queue_name}",
            *(f"job-lease:{job_id}" for job_id in job_ids),
        )
        redis_client.close()
        session.close()
        transaction.rollback()
        connection.close()


def register_claim_worker(worker_id: str, capability: str) -> httpx.Response:
    return gateway_request(
        "POST",
        "/worker/v1/workers/register",
        request_body={"worker_id": worker_id, "capabilities": [capability]},
    )


def create_ready_job(
    session: Session,
    queue: RedisQueue,
    queue_name: str,
    *,
    max_attempts: int = 5,
) -> Job:
    repository = JobRepository(session)
    job = repository.create(
        job_type="generate_report",
        queue=queue_name,
        payload={"report_id": 42},
        max_attempts=max_attempts,
    )
    repository.transition(job, JobStatus.QUEUED)
    queue.enqueue(job.id, queue=queue_name, priority=job.priority)
    return job


def claim_ready_job(
    session: Session,
    queue: RedisQueue,
    queue_name: str,
    *,
    worker_id: str = "worker-1",
    max_attempts: int = 5,
) -> tuple[Job, dict]:
    assert register_claim_worker(worker_id, "generate_report").status_code == 201
    job = create_ready_job(
        session,
        queue,
        queue_name,
        max_attempts=max_attempts,
    )
    response = gateway_request(
        "POST",
        "/worker/v1/jobs/claim",
        request_body={
            "worker_id": worker_id,
            "queue": queue_name,
            "wait_seconds": 0,
        },
    )
    assert response.status_code == 200
    return job, response.json()


@pytest.mark.parametrize("token", [None, "wrong-worker-token"])
def test_worker_gateway_requires_valid_bearer_token(gateway_context, token):
    _ = gateway_context

    response = gateway_request(
        "POST",
        "/worker/v1/workers/register",
        request_body={"worker_id": "worker-1", "capabilities": ["reports"]},
        token=token,
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid worker token"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_register_worker_through_gateway(gateway_context):
    session = gateway_context

    response = gateway_request(
        "POST",
        "/worker/v1/workers/register",
        request_body={
            "worker_id": "report-worker-1",
            "capabilities": ["generate_report", "generate_report", "export_csv"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["worker_id"] == "report-worker-1"
    assert body["capabilities"] == ["export_csv", "generate_report"]
    assert body["status"] == WorkerStatus.ONLINE.value
    assert body["heartbeat_interval_seconds"] == 10
    assert body["registered_at"]
    assert body["last_heartbeat_at"]

    worker = session.get(Worker, "report-worker-1")
    assert worker is not None
    assert worker.capabilities == ["export_csv", "generate_report"]


@pytest.mark.parametrize(
    "request_body",
    [
        {"worker_id": "", "capabilities": ["reports"]},
        {"worker_id": "worker with spaces", "capabilities": ["reports"]},
        {"worker_id": "worker-1", "capabilities": []},
        {"worker_id": "worker-1", "capabilities": ["invalid capability"]},
    ],
)
def test_register_worker_validates_identity_and_capabilities(
    gateway_context, request_body
):
    _ = gateway_context

    response = gateway_request(
        "POST", "/worker/v1/workers/register", request_body=request_body
    )

    assert response.status_code == 422


def test_heartbeat_updates_registered_worker(gateway_context):
    session = gateway_context
    registered = gateway_request(
        "POST",
        "/worker/v1/workers/register",
        request_body={"worker_id": "worker-1", "capabilities": ["reports"]},
    ).json()
    registered_at = datetime.fromisoformat(registered["last_heartbeat_at"])

    response = gateway_request(
        "POST", "/worker/v1/workers/worker-1/heartbeat"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["worker_id"] == "worker-1"
    assert body["status"] == WorkerStatus.ONLINE.value
    heartbeat_at = datetime.fromisoformat(body["last_heartbeat_at"])
    assert heartbeat_at >= registered_at
    session.expire_all()
    worker = session.get(Worker, "worker-1")
    assert worker is not None
    assert worker.last_heartbeat_at >= registered_at


def test_heartbeat_rejects_unknown_worker(gateway_context):
    _ = gateway_context

    response = gateway_request(
        "POST", "/worker/v1/workers/missing-worker/heartbeat"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Worker not found"}


def test_gateway_claims_job_and_persists_running_handoff(claim_gateway_context):
    session, queue, _, queue_name = claim_gateway_context
    assert register_claim_worker("worker-1", "generate_report").status_code == 201
    job = create_ready_job(session, queue, queue_name)

    response = gateway_request(
        "POST",
        "/worker/v1/jobs/claim",
        request_body={
            "worker_id": "worker-1",
            "queue": queue_name,
            "wait_seconds": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job.id
    assert body["attempt_number"] == 1
    assert body["type"] == "generate_report"
    assert body["queue"] == queue_name
    assert body["payload"] == {"report_id": 42}
    assert body["lease_token"]
    assert body["lease_expires_at"]
    session.expire_all()
    running = session.get(Job, job.id)
    assert running is not None
    assert running.status == JobStatus.RUNNING.value
    assert running.worker_id == "worker-1"
    assert running.lease_token == body["lease_token"]
    attempt = session.scalar(
        select(JobAttempt).where(JobAttempt.job_id == job.id)
    )
    assert attempt is not None
    assert attempt.attempt_number == 1
    assert attempt.status == JobStatus.RUNNING.value
    assert queue.inflight_size(queue_name) == 1


def test_gateway_claim_returns_no_content_when_queue_is_empty(
    claim_gateway_context,
):
    _, _, _, queue_name = claim_gateway_context
    assert register_claim_worker("worker-1", "generate_report").status_code == 201

    response = gateway_request(
        "POST",
        "/worker/v1/jobs/claim",
        request_body={
            "worker_id": "worker-1",
            "queue": queue_name,
            "wait_seconds": 0,
        },
    )

    assert response.status_code == 204
    assert response.content == b""


def test_gateway_claim_rejects_unregistered_worker(claim_gateway_context):
    _, _, _, queue_name = claim_gateway_context

    response = gateway_request(
        "POST",
        "/worker/v1/jobs/claim",
        request_body={
            "worker_id": "missing-worker",
            "queue": queue_name,
            "wait_seconds": 0,
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Worker missing-worker is not registered"
    }


def test_gateway_returns_incompatible_job_to_ready(claim_gateway_context):
    session, queue, _, queue_name = claim_gateway_context
    assert register_claim_worker("worker-1", "resize_image").status_code == 201
    job = create_ready_job(session, queue, queue_name)

    response = gateway_request(
        "POST",
        "/worker/v1/jobs/claim",
        request_body={
            "worker_id": "worker-1",
            "queue": queue_name,
            "wait_seconds": 0,
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Worker worker-1 does not support generate_report"
    }
    session.expire_all()
    queued = session.get(Job, job.id)
    assert queued is not None
    assert queued.status == JobStatus.QUEUED.value
    assert queue.queue_size(queue_name) == 1
    assert queue.inflight_size(queue_name) == 0


def test_gateway_renews_fenced_lease(claim_gateway_context):
    session, queue, _, queue_name = claim_gateway_context
    job, claimed = claim_ready_job(session, queue, queue_name)
    previous_expiry = datetime.fromisoformat(claimed["lease_expires_at"])

    response = gateway_request(
        "POST",
        f"/worker/v1/jobs/{job.id}/lease/renew",
        request_body={
            "worker_id": "worker-1",
            "lease_token": claimed["lease_token"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job.id
    assert body["worker_id"] == "worker-1"
    renewed_expiry = datetime.fromisoformat(body["lease_expires_at"])
    assert renewed_expiry >= previous_expiry
    session.expire_all()
    running = session.get(Job, job.id)
    assert running is not None
    assert running.lease_expires_at == renewed_expiry
    assert queue.lease_ttl(job.id) > 0


def test_gateway_rejects_stale_lease_token(claim_gateway_context):
    session, queue, _, queue_name = claim_gateway_context
    job, claimed = claim_ready_job(session, queue, queue_name)

    response = gateway_request(
        "POST",
        f"/worker/v1/jobs/{job.id}/lease/renew",
        request_body={
            "worker_id": "worker-1",
            "lease_token": str(uuid4()),
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": f"Worker no longer owns job {job.id}"
    }
    session.expire_all()
    running = session.get(Job, job.id)
    assert running is not None
    assert running.lease_token == claimed["lease_token"]


def test_gateway_reports_lease_loss_when_redis_lease_is_missing(
    claim_gateway_context,
):
    session, queue, redis_client, queue_name = claim_gateway_context
    job, claimed = claim_ready_job(session, queue, queue_name)
    redis_client.delete(f"job-lease:{job.id}")

    response = gateway_request(
        "POST",
        f"/worker/v1/jobs/{job.id}/lease/renew",
        request_body={
            "worker_id": "worker-1",
            "lease_token": claimed["lease_token"],
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": f"Worker no longer owns job {job.id}"
    }


def test_gateway_rejects_malformed_lease_token(claim_gateway_context):
    _, _, _, _ = claim_gateway_context

    response = gateway_request(
        "POST",
        f"/worker/v1/jobs/{uuid4()}/lease/renew",
        request_body={
            "worker_id": "worker-1",
            "lease_token": "not-a-uuid",
        },
    )

    assert response.status_code == 422


def test_gateway_completes_job_and_accepts_identical_replay(
    claim_gateway_context,
):
    session, queue, _, queue_name = claim_gateway_context
    job, claimed = claim_ready_job(session, queue, queue_name)
    request_body = {
        "worker_id": "worker-1",
        "lease_token": claimed["lease_token"],
        "result_ref": "results/job-output.json",
    }

    first = gateway_request(
        "POST",
        f"/worker/v1/jobs/{job.id}/complete",
        request_body=request_body,
    )
    replay = gateway_request(
        "POST",
        f"/worker/v1/jobs/{job.id}/complete",
        request_body=request_body,
    )

    assert first.status_code == 200
    assert first.json() == {
        "job_id": job.id,
        "status": JobStatus.COMPLETED.value,
        "attempt_number": 1,
        "result_ref": "results/job-output.json",
        "error": None,
        "replayed": False,
    }
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    session.expire_all()
    completed = session.get(Job, job.id)
    assert completed is not None
    assert completed.status == JobStatus.COMPLETED.value
    assert completed.result_ref == "results/job-output.json"
    attempt = session.scalar(
        select(JobAttempt).where(JobAttempt.job_id == job.id)
    )
    assert attempt is not None
    assert attempt.status == JobStatus.COMPLETED.value
    assert attempt.lease_token == claimed["lease_token"]
    assert queue.inflight_size(queue_name) == 0


def test_gateway_rejects_changed_completion_replay(claim_gateway_context):
    session, queue, _, queue_name = claim_gateway_context
    job, claimed = claim_ready_job(session, queue, queue_name)
    original = {
        "worker_id": "worker-1",
        "lease_token": claimed["lease_token"],
        "result_ref": "results/original.json",
    }
    assert gateway_request(
        "POST",
        f"/worker/v1/jobs/{job.id}/complete",
        request_body=original,
    ).status_code == 200

    changed = gateway_request(
        "POST",
        f"/worker/v1/jobs/{job.id}/complete",
        request_body={**original, "result_ref": "results/different.json"},
    )

    assert changed.status_code == 409
    assert changed.json() == {
        "detail": f"Worker no longer owns job {job.id}"
    }


def test_gateway_records_failure_and_accepts_identical_replay(
    claim_gateway_context,
):
    session, queue, _, queue_name = claim_gateway_context
    job, claimed = claim_ready_job(session, queue, queue_name)
    request_body = {
        "worker_id": "worker-1",
        "lease_token": claimed["lease_token"],
        "error": {
            "type": "RuntimeError",
            "message": "report service unavailable",
            "details": {"upstream": "reports"},
        },
    }

    first = gateway_request(
        "POST",
        f"/worker/v1/jobs/{job.id}/fail",
        request_body=request_body,
    )
    replay = gateway_request(
        "POST",
        f"/worker/v1/jobs/{job.id}/fail",
        request_body=request_body,
    )

    assert first.status_code == 200
    assert first.json()["status"] == JobStatus.RETRY_WAIT.value
    assert first.json()["error"] == request_body["error"]
    assert first.json()["replayed"] is False
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    session.expire_all()
    failed = session.get(Job, job.id)
    assert failed is not None
    assert failed.status == JobStatus.RETRY_WAIT.value
    assert failed.error == request_body["error"]
    assert queue.inflight_size(queue_name) == 0


def test_gateway_marks_exhausted_failure_terminal(claim_gateway_context):
    session, queue, _, queue_name = claim_gateway_context
    job, claimed = claim_ready_job(
        session,
        queue,
        queue_name,
        max_attempts=1,
    )

    response = gateway_request(
        "POST",
        f"/worker/v1/jobs/{job.id}/fail",
        request_body={
            "worker_id": "worker-1",
            "lease_token": claimed["lease_token"],
            "error": {"type": "ValueError", "message": "invalid report"},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == JobStatus.FAILED.value
    session.expire_all()
    failed = session.get(Job, job.id)
    assert failed is not None
    assert failed.status == JobStatus.FAILED.value


def test_gateway_completion_remains_durable_when_redis_lease_is_missing(
    claim_gateway_context,
):
    session, queue, redis_client, queue_name = claim_gateway_context
    job, claimed = claim_ready_job(session, queue, queue_name)
    redis_client.delete(f"job-lease:{job.id}")

    response = gateway_request(
        "POST",
        f"/worker/v1/jobs/{job.id}/complete",
        request_body={
            "worker_id": "worker-1",
            "lease_token": claimed["lease_token"],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == JobStatus.COMPLETED.value
    session.expire_all()
    completed = session.get(Job, job.id)
    assert completed is not None
    assert completed.status == JobStatus.COMPLETED.value
