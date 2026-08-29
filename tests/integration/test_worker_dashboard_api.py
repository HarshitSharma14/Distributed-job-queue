import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from distributed_job_queue.api.app import app
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.auth.security import hash_password
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import Job, JobAttempt, User, Worker
from distributed_job_queue.persistence.repositories import IdentityRepository, JobRepository

PASSWORD = "correct-horse-battery-staple"


@dataclass(frozen=True)
class WorkerDashboardContext:
    session: Session
    worker_user: User
    producer_only: User
    first_worker_id: str
    second_worker_id: str
    job_type_id: str
    assignments: tuple[Job, Job]
    attempts: tuple[JobAttempt, JobAttempt, JobAttempt, JobAttempt]


@pytest.fixture
def worker_dashboard_context():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    identities = IdentityRepository(session)
    jobs = JobRepository(session)

    def user(name: str, role: UserRole) -> User:
        created = identities.create_user(
            email=f"{name}-{uuid4()}@example.com",
            display_name=name.title(),
            password_hash=hash_password(PASSWORD),
        )
        identities.assign_role(created, role)
        return created

    worker_user = user("worker-dashboard", UserRole.WORKER)
    other_worker_user = user("other-worker", UserRole.WORKER)
    producer_only = user("producer-only", UserRole.PRODUCER)
    publisher = user("worker-dashboard-publisher", UserRole.PUBLISHER)
    job_type = identities.create_job_type(
        publisher_id=publisher.id,
        name="generate_report",
        queue="reports",
    )
    first_worker = Worker(
        id=f"worker-a-{uuid4().hex}",
        owner_user_id=worker_user.id,
        capabilities=[job_type.name],
    )
    second_worker = Worker(
        id=f"worker-b-{uuid4().hex}",
        owner_user_id=worker_user.id,
        capabilities=[job_type.name],
    )
    hidden_worker = Worker(
        id=f"hidden-worker-{uuid4().hex}",
        owner_user_id=other_worker_user.id,
        capabilities=[job_type.name],
    )
    session.add_all([first_worker, second_worker, hidden_worker])
    session.flush()
    base_time = datetime(2026, 8, 29, 18, 0, tzinfo=timezone.utc)

    def job(worker: Worker, label: str, status: JobStatus, hours_ago: int) -> Job:
        created = jobs.create(
            job_type=job_type.name,
            job_type_id=job_type.id,
            publisher_id=publisher.id,
            producer_id=producer_only.id,
            queue=job_type.queue,
            payload={"private": label},
        )
        created.status = status.value
        created.worker_id = worker.id
        created.created_at = base_time - timedelta(hours=hours_ago, minutes=10)
        created.updated_at = base_time - timedelta(hours=hours_ago)
        created.lease_expires_at = (
            base_time + timedelta(minutes=5)
            if status == JobStatus.RUNNING
            else None
        )
        return created

    completed_job = job(first_worker, "completed", JobStatus.COMPLETED, 4)
    completed_job.attempts = 1
    completed_job.completed_at = completed_job.updated_at
    first_assignment = job(first_worker, "running-a", JobStatus.RUNNING, 2)
    first_assignment.attempts = 2
    second_assignment = job(second_worker, "running-b", JobStatus.RUNNING, 1)
    second_assignment.attempts = 1
    hidden_assignment = job(hidden_worker, "hidden", JobStatus.RUNNING, 0)
    hidden_assignment.attempts = 1

    completed_attempt = JobAttempt(
        job_id=completed_job.id,
        worker_id=first_worker.id,
        lease_token=str(uuid4()),
        attempt_number=1,
        status=JobStatus.COMPLETED.value,
        started_at=base_time - timedelta(hours=4, seconds=5),
        finished_at=base_time - timedelta(hours=4),
    )
    failed_attempt = JobAttempt(
        job_id=first_assignment.id,
        worker_id=first_worker.id,
        lease_token=str(uuid4()),
        attempt_number=1,
        status=JobStatus.FAILED.value,
        started_at=base_time - timedelta(hours=3),
        finished_at=base_time - timedelta(hours=3) + timedelta(seconds=2),
        error={"type": "TemporaryFailure", "message": "retry"},
    )
    running_attempt = JobAttempt(
        job_id=first_assignment.id,
        worker_id=first_worker.id,
        lease_token=str(uuid4()),
        attempt_number=2,
        status=JobStatus.RUNNING.value,
        started_at=base_time - timedelta(hours=2),
    )
    second_running_attempt = JobAttempt(
        job_id=second_assignment.id,
        worker_id=second_worker.id,
        lease_token=str(uuid4()),
        attempt_number=1,
        status=JobStatus.RUNNING.value,
        started_at=base_time - timedelta(hours=1),
    )
    hidden_attempt = JobAttempt(
        job_id=hidden_assignment.id,
        worker_id=hidden_worker.id,
        lease_token=str(uuid4()),
        attempt_number=1,
        status=JobStatus.RUNNING.value,
        started_at=base_time,
    )
    session.add_all(
        [
            completed_attempt,
            failed_attempt,
            running_attempt,
            second_running_attempt,
            hidden_attempt,
        ]
    )
    session.flush()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield WorkerDashboardContext(
            session=session,
            worker_user=worker_user,
            producer_only=producer_only,
            first_worker_id=first_worker.id,
            second_worker_id=second_worker.id,
            job_type_id=job_type.id,
            assignments=(first_assignment, second_assignment),
            attempts=(
                completed_attempt,
                failed_attempt,
                running_attempt,
                second_running_attempt,
            ),
        )
    finally:
        app.dependency_overrides.clear()
        session.close()
        transaction.rollback()
        connection.close()


async def login(client: httpx.AsyncClient, user: User) -> None:
    response = await client.post(
        "/auth/login",
        json={"email": user.email, "password": PASSWORD},
    )
    assert response.status_code == 200


def test_worker_assignments_are_active_owned_and_filterable(worker_dashboard_context):
    context = worker_dashboard_context

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, context.worker_user)
            response = await client.get(
                "/worker-management/assignments", params={"limit": 1}
            )
            assert response.status_code == 200
            body = response.json()
            assert [item["job_id"] for item in body["items"]] == [
                context.assignments[1].id
            ]
            assert body["next_cursor"]
            assert all(item["status"] == "RUNNING" for item in body["items"])
            assert "payload" not in body["items"][0]
            assert "lease_token" not in body["items"][0]

            second_page = await client.get(
                "/worker-management/assignments",
                params={"limit": 1, "cursor": body["next_cursor"]},
            )
            assert [item["job_id"] for item in second_page.json()["items"]] == [
                context.assignments[0].id
            ]
            assert second_page.json()["next_cursor"] is None

            filtered = await client.get(
                "/worker-management/assignments",
                params={"worker_id": context.first_worker_id},
            )
            assert [item["job_id"] for item in filtered.json()["items"]] == [
                context.assignments[0].id
            ]

    asyncio.run(scenario())


def test_worker_attempt_history_is_owned_paginated_and_filtered(
    worker_dashboard_context,
):
    context = worker_dashboard_context

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, context.worker_user)
            first = await client.get(
                "/worker-management/attempts", params={"limit": 2}
            )
            assert first.status_code == 200
            first_body = first.json()
            assert [item["attempt_id"] for item in first_body["items"]] == [
                context.attempts[3].id,
                context.attempts[2].id,
            ]
            assert first_body["next_cursor"]
            assert "payload" not in first_body["items"][0]
            assert "result_ref" not in first_body["items"][0]
            assert "lease_token" not in first_body["items"][0]

            second = await client.get(
                "/worker-management/attempts",
                params={"limit": 2, "cursor": first_body["next_cursor"]},
            )
            assert [item["attempt_id"] for item in second.json()["items"]] == [
                context.attempts[1].id,
                context.attempts[0].id,
            ]
            assert second.json()["next_cursor"] is None
            assert second.json()["items"][0]["duration_ms"] == 2_000.0
            assert second.json()["items"][1]["duration_ms"] == 5_000.0

            failed = await client.get(
                "/worker-management/attempts", params={"status": "FAILED"}
            )
            assert [item["attempt_id"] for item in failed.json()["items"]] == [
                context.attempts[1].id
            ]
            assert failed.json()["items"][0]["error"]["type"] == "TemporaryFailure"

    asyncio.run(scenario())


def test_worker_dashboard_requires_worker_role_and_valid_cursor(
    worker_dashboard_context,
):
    context = worker_dashboard_context

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as anonymous:
            assert (
                await anonymous.get("/worker-management/attempts")
            ).status_code == 401

        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as producer_client:
            await login(producer_client, context.producer_only)
            forbidden = await producer_client.get("/worker-management/assignments")
            assert forbidden.status_code == 403
            assert forbidden.json()["error"]["code"] == "WORKER_ROLE_REQUIRED"

        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as worker_client:
            await login(worker_client, context.worker_user)
            invalid = await worker_client.get(
                "/worker-management/attempts", params={"cursor": "invalid"}
            )
            assert invalid.status_code == 400
            assert (
                invalid.json()["error"]["code"]
                == "WORKER_DASHBOARD_FILTER_INVALID"
            )

    asyncio.run(scenario())
