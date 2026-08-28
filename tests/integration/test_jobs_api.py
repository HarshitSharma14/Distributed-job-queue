import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from distributed_job_queue.api.app import app
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import Job, OutboxEvent, Worker
from distributed_job_queue.persistence.repositories import JobRepository


@pytest.fixture
def api_context():
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


def api_request(
    method: str,
    path: str,
    *,
    request_body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(
                method, path, json=request_body, headers=headers
            )

    return asyncio.run(send_request())


def post_job(
    request_body: dict, *, idempotency_key: str | None = None
) -> httpx.Response:
    headers = (
        {"Idempotency-Key": idempotency_key}
        if idempotency_key is not None
        else None
    )
    return api_request(
        "POST", "/jobs", request_body=request_body, headers=headers
    )


def test_submit_job_creates_job_and_outbox_event_atomically(api_context):
    session = api_context

    response = post_job(
        {
            "type": "generate_report",
            "queue": "reports",
            "payload": {"report_id": 42},
            "priority": 8,
            "max_attempts": 3,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == JobStatus.CREATED.value
    assert body["type"] == "generate_report"
    assert body["queue"] == "reports"
    assert body["priority"] == 8
    assert body["created_at"]

    job = session.get(Job, body["job_id"])
    assert job is not None
    assert job.payload == {"report_id": 42}
    assert job.max_attempts == 3
    event = session.scalar(
        select(OutboxEvent).where(OutboxEvent.job_id == job.id)
    )
    assert event is not None
    assert event.event_type == "JOB_READY"
    assert event.payload == {
        "job_id": job.id,
        "queue": "reports",
        "priority": 8,
    }
    assert event.published_at is None


def test_submit_job_uses_safe_defaults(api_context):
    session = api_context

    response = post_job(
        {"type": "send_email", "payload": {"user_id": 123}},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["queue"] == "default"
    assert body["priority"] == 0
    job = session.get(Job, body["job_id"])
    assert job is not None
    assert job.max_attempts == 5


@pytest.mark.parametrize(
    "request_body",
    [
        {"type": "", "payload": {}},
        {"type": "send email", "payload": {}},
        {"type": "send_email", "queue": "invalid queue", "payload": {}},
        {"type": "send_email", "payload": [], "priority": 0},
        {"type": "send_email", "payload": {}, "priority": -1},
        {"type": "send_email", "payload": {}, "max_attempts": 0},
    ],
)
def test_submit_job_rejects_invalid_requests(api_context, request_body):
    _ = api_context

    response = post_job(request_body)

    assert response.status_code == 422


def test_get_job_returns_authoritative_state(api_context):
    _ = api_context
    created = post_job(
        {
            "type": "generate_report",
            "queue": "reports",
            "payload": {"report_id": 42},
        }
    ).json()

    response = api_request("GET", f"/jobs/{created['job_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == created["job_id"]
    assert body["status"] == JobStatus.CREATED.value
    assert body["payload"] == {"report_id": 42}
    assert body["attempt_count"] == 0
    assert body["attempt_history"] == []
    assert body["dead_lettered_at"] is None
    assert "lease_token" not in body


def test_get_job_returns_ordered_attempt_history(api_context):
    session = api_context
    created = post_job(
        {"type": "generate_report", "queue": "reports", "payload": {}}
    ).json()
    worker = Worker(id=f"detail-worker-{uuid4()}", capabilities=["generate_report"])
    session.add(worker)
    session.flush()
    repository = JobRepository(session)
    job = repository.get(created["job_id"])
    assert job is not None
    repository.transition(job, JobStatus.QUEUED)
    lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    repository.mark_running(
        job.id,
        worker_id=worker.id,
        lease_token="private-token",
        lease_expires_at=lease_expires_at,
    )

    response = api_request("GET", f"/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == JobStatus.RUNNING.value
    assert body["worker_id"] == worker.id
    assert body["lease_expires_at"]
    assert body["attempt_count"] == 1
    assert len(body["attempt_history"]) == 1
    attempt = body["attempt_history"][0]
    assert attempt["attempt_number"] == 1
    assert attempt["worker_id"] == worker.id
    assert attempt["status"] == JobStatus.RUNNING.value
    assert attempt["started_at"]
    assert attempt["finished_at"] is None
    assert attempt["error"] is None
    assert "lease_token" not in body


def test_get_job_returns_not_found_for_unknown_uuid(api_context):
    _ = api_context

    response = api_request("GET", f"/jobs/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}


def test_get_job_rejects_malformed_id(api_context):
    _ = api_context

    response = api_request("GET", "/jobs/not-a-uuid")

    assert response.status_code == 422


def test_submit_job_replays_same_idempotent_request(api_context):
    session = api_context
    request_body = {
        "type": "generate_report",
        "queue": "reports",
        "payload": {"report_id": 42},
    }

    first = post_job(request_body, idempotency_key="report-request-42")
    second = post_job(request_body, idempotency_key="report-request-42")

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert "Idempotency-Replayed" not in first.headers
    assert second.headers["Idempotency-Replayed"] == "true"
    jobs = list(
        session.scalars(
            select(Job).where(Job.idempotency_key == "report-request-42")
        )
    )
    assert len(jobs) == 1
    events = list(
        session.scalars(
            select(OutboxEvent).where(OutboxEvent.job_id == jobs[0].id)
        )
    )
    assert len(events) == 1


def test_submit_job_rejects_idempotency_key_reuse_for_different_work(api_context):
    _ = api_context
    first = post_job(
        {"type": "generate_report", "payload": {"report_id": 42}},
        idempotency_key="report-conflict",
    )

    second = post_job(
        {"type": "generate_report", "payload": {"report_id": 43}},
        idempotency_key="report-conflict",
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json() == {
        "detail": "Idempotency-Key was already used for a different request"
    }


def test_submit_job_rejects_invalid_idempotency_key(api_context):
    _ = api_context

    response = post_job(
        {"type": "send_email", "payload": {}},
        idempotency_key="spaces are not allowed",
    )

    assert response.status_code == 422
