import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from prometheus_client import REGISTRY
from sqlalchemy import select
from sqlalchemy.orm import Session

from distributed_job_queue.api.app import app
from distributed_job_queue.api.auth_dependencies import require_job_read_principal
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.auth.service import (
    AuthenticatedPrincipal,
    CredentialKind,
    issue_producer_key,
)
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import Job, OutboxEvent, Worker
from distributed_job_queue.persistence.repositories import IdentityRepository, JobRepository


@dataclass(frozen=True)
class APIContext:
    session: Session
    publisher_id: str
    producer_id: str
    job_type_id: str
    api_key: str


def assert_api_error(response: httpx.Response, *, code: str, message: str) -> None:
    error = response.json()["error"]
    assert error["code"] == code
    assert error["message"] == message
    assert error["request_id"] == response.headers["x-request-id"]


@pytest.fixture
def api_context():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    identities = IdentityRepository(session)
    publisher = identities.create_user(
        email=f"publisher-{uuid4()}@example.com", display_name="Publisher"
    )
    producer = identities.create_user(
        email=f"producer-{uuid4()}@example.com", display_name="Producer"
    )
    identities.assign_role(publisher, UserRole.PUBLISHER)
    identities.assign_role(producer, UserRole.PRODUCER)
    job_type = identities.create_job_type(
        publisher_id=publisher.id,
        name="generate_report",
        queue="reports",
    )
    api_key = issue_producer_key(
        session,
        user_id=producer.id,
        name="Integration tests",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ).raw_key

    def override_session():
        yield session

    context = APIContext(
            session=session,
            publisher_id=publisher.id,
            producer_id=producer.id,
            job_type_id=job_type.id,
            api_key=api_key,
    )

    app.dependency_overrides[get_session] = override_session
    try:
        yield context
    finally:
        app.dependency_overrides.clear()
        session.close()
        transaction.rollback()
        connection.close()


def api_request(
    context: APIContext | None,
    method: str,
    path: str,
    *,
    request_body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request_headers = dict(headers or {})
    if context is not None:
        request_headers.setdefault("Authorization", f"Bearer {context.api_key}")

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(
                method, path, json=request_body, headers=request_headers
            )

    return asyncio.run(send_request())


def post_job(
    context: APIContext,
    request_body: dict,
    *,
    idempotency_key: str | None = None,
) -> httpx.Response:
    headers = (
        {"Idempotency-Key": idempotency_key}
        if idempotency_key is not None
        else None
    )
    return api_request(
        context, "POST", "/jobs", request_body=request_body, headers=headers
    )


def test_submit_job_creates_job_and_outbox_event_atomically(api_context):
    session = api_context.session

    response = post_job(
        api_context,
        {
            "job_type_id": api_context.job_type_id,
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
    assert job.job_type_id == api_context.job_type_id
    assert job.publisher_id == api_context.publisher_id
    assert job.producer_id == api_context.producer_id
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
    session = api_context.session

    response = post_job(
        api_context,
        {"job_type_id": api_context.job_type_id, "payload": {"user_id": 123}},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["queue"] == "reports"
    assert body["priority"] == 0
    job = session.get(Job, body["job_id"])
    assert job is not None
    assert job.max_attempts == 5


@pytest.mark.parametrize(
    "request_body",
    [
        {"payload": {}},
        {"job_type_id": "not-a-uuid", "payload": {}},
        {"job_type_id": str(uuid4()), "type": "forbidden", "payload": {}},
        {"job_type_id": str(uuid4()), "payload": [], "priority": 0},
        {"job_type_id": str(uuid4()), "payload": {}, "priority": -1},
        {"job_type_id": str(uuid4()), "payload": {}, "max_attempts": 0},
    ],
)
def test_submit_job_rejects_invalid_requests(api_context, request_body):
    _ = api_context

    response = post_job(api_context, request_body)

    assert response.status_code == 422


def test_get_job_returns_authoritative_state(api_context):
    created = post_job(
        api_context,
        {
            "job_type_id": api_context.job_type_id,
            "payload": {"report_id": 42},
        }
    ).json()

    response = api_request(api_context, "GET", f"/jobs/{created['job_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == created["job_id"]
    assert body["job_type_id"] == api_context.job_type_id
    assert body["publisher_id"] == api_context.publisher_id
    assert body["producer_id"] == api_context.producer_id
    assert body["status"] == JobStatus.CREATED.value
    assert body["payload"] == {"report_id": 42}
    assert body["attempt_count"] == 0
    assert body["attempt_history"] == []
    assert body["dead_lettered_at"] is None
    assert "lease_token" not in body


def test_get_job_returns_ordered_attempt_history(api_context):
    session = api_context.session
    created = post_job(
        api_context,
        {"job_type_id": api_context.job_type_id, "payload": {}},
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

    response = api_request(api_context, "GET", f"/jobs/{job.id}")

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

    response = api_request(
        api_context,
        "GET",
        f"/jobs/{uuid4()}",
        headers={"X-Request-ID": "client-request-123"},
    )

    assert response.status_code == 404
    assert response.headers["x-request-id"] == "client-request-123"
    assert_api_error(response, code="JOB_NOT_FOUND", message="Job not found")


def test_get_job_rejects_malformed_id(api_context):
    _ = api_context

    response = api_request(api_context, "GET", "/jobs/not-a-uuid")

    assert response.status_code == 422
    assert_api_error(
        response,
        code="VALIDATION_ERROR",
        message="Request validation failed",
    )


def test_submit_job_replays_same_idempotent_request(api_context):
    session = api_context.session
    request_body = {
        "job_type_id": api_context.job_type_id,
        "payload": {"report_id": 42},
    }
    labels = {"queue": "reports"}
    before = REGISTRY.get_sample_value("djq_jobs_submitted_total", labels) or 0

    first = post_job(api_context, request_body, idempotency_key="report-request-42")
    second = post_job(api_context, request_body, idempotency_key="report-request-42")

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
    assert REGISTRY.get_sample_value("djq_jobs_submitted_total", labels) == before + 1


def test_submit_job_rejects_idempotency_key_reuse_for_different_work(api_context):
    first = post_job(
        api_context,
        {"job_type_id": api_context.job_type_id, "payload": {"report_id": 42}},
        idempotency_key="report-conflict",
    )

    second = post_job(
        api_context,
        {"job_type_id": api_context.job_type_id, "payload": {"report_id": 43}},
        idempotency_key="report-conflict",
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert_api_error(
        second,
        code="IDEMPOTENCY_CONFLICT",
        message="Idempotency-Key was already used for a different request",
    )


def test_submit_job_rejects_invalid_idempotency_key(api_context):
    response = post_job(
        api_context,
        {"job_type_id": api_context.job_type_id, "payload": {}},
        idempotency_key="spaces are not allowed",
    )

    assert response.status_code == 422


def test_job_routes_require_authentication(api_context):
    response = api_request(None, "GET", f"/jobs/{uuid4()}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_submit_job_rejects_unknown_job_type(api_context):
    response = post_job(
        api_context,
        {"job_type_id": str(uuid4()), "payload": {}},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_TYPE_NOT_FOUND"


def test_producer_cannot_read_another_producers_job(api_context):
    created = post_job(
        api_context,
        {"job_type_id": api_context.job_type_id, "payload": {}},
    ).json()
    identities = IdentityRepository(api_context.session)
    other_producer = identities.create_user(
        email=f"other-producer-{uuid4()}@example.com",
        display_name="Other Producer",
    )
    identities.assign_role(other_producer, UserRole.PRODUCER)
    other_key = issue_producer_key(
        api_context.session,
        user_id=other_producer.id,
        name="Other producer key",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ).raw_key
    other_context = APIContext(
        session=api_context.session,
        publisher_id=api_context.publisher_id,
        producer_id=other_producer.id,
        job_type_id=api_context.job_type_id,
        api_key=other_key,
    )

    response = api_request(other_context, "GET", f"/jobs/{created['job_id']}")

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("user_id_source", "roles", "expected_status"),
    [
        ("publisher", frozenset({UserRole.PUBLISHER}), 200),
        ("unrelated", frozenset({UserRole.PUBLISHER}), 404),
        ("unrelated", frozenset({UserRole.ADMIN}), 200),
    ],
)
def test_publisher_and_admin_job_visibility(
    api_context, user_id_source, roles, expected_status
):
    created = post_job(
        api_context,
        {"job_type_id": api_context.job_type_id, "payload": {}},
    ).json()
    user_id = (
        api_context.publisher_id
        if user_id_source == "publisher"
        else str(uuid4())
    )
    principal = AuthenticatedPrincipal(
        user_id=user_id,
        email="viewer@example.com",
        display_name="Viewer",
        roles=roles,
        credential_kind=CredentialKind.BROWSER_SESSION,
    )
    app.dependency_overrides[require_job_read_principal] = lambda: principal
    try:
        response = api_request(None, "GET", f"/jobs/{created['job_id']}")
    finally:
        app.dependency_overrides.pop(require_job_read_principal, None)

    assert response.status_code == expected_status
