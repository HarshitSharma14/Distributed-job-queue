import asyncio

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from distributed_job_queue.api.app import app
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import Job, OutboxEvent


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


def post_job(request_body: dict) -> httpx.Response:
    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.post("/jobs", json=request_body)

    return asyncio.run(send_request())


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
