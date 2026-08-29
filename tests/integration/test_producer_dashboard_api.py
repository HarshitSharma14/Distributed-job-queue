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
from distributed_job_queue.auth.service import issue_producer_key
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import Job, User
from distributed_job_queue.persistence.repositories import IdentityRepository, JobRepository

PASSWORD = "correct-horse-battery-staple"


@dataclass(frozen=True)
class ProducerDashboardContext:
    session: Session
    producer: User
    publisher_only: User
    first_publisher_id: str
    second_publisher_id: str
    jobs: tuple[Job, Job, Job]
    api_key: str
    no_read_api_key: str


@pytest.fixture
def producer_dashboard_context():
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

    producer = user("producer-dashboard", UserRole.PRODUCER)
    other_producer = user("other-producer", UserRole.PRODUCER)
    first_publisher = user("first-publisher", UserRole.PUBLISHER)
    second_publisher = user("second-publisher", UserRole.PUBLISHER)
    publisher_only = user("publisher-only", UserRole.PUBLISHER)
    report_type = identities.create_job_type(
        publisher_id=first_publisher.id,
        name="generate_report",
        queue="reports",
    )
    image_type = identities.create_job_type(
        publisher_id=second_publisher.id,
        name="resize_image",
        queue="images",
    )
    base_time = datetime(2026, 8, 29, 15, 0, tzinfo=timezone.utc)

    completed = jobs.create(
        job_type=report_type.name,
        job_type_id=report_type.id,
        publisher_id=first_publisher.id,
        producer_id=producer.id,
        queue=report_type.queue,
        payload={"request": "completed"},
    )
    completed.status = JobStatus.COMPLETED.value
    completed.attempts = 1
    completed.created_at = base_time - timedelta(hours=3)
    completed.updated_at = completed.created_at + timedelta(seconds=5)
    completed.completed_at = completed.updated_at

    running = jobs.create(
        job_type=image_type.name,
        job_type_id=image_type.id,
        publisher_id=second_publisher.id,
        producer_id=producer.id,
        queue=image_type.queue,
        payload={"request": "running"},
    )
    running.status = JobStatus.RUNNING.value
    running.attempts = 1
    running.created_at = base_time - timedelta(hours=2)
    running.updated_at = running.created_at + timedelta(seconds=10)

    dead_lettered = jobs.create(
        job_type=report_type.name,
        job_type_id=report_type.id,
        publisher_id=first_publisher.id,
        producer_id=producer.id,
        queue=report_type.queue,
        payload={"request": "dead"},
    )
    dead_lettered.status = JobStatus.DEAD_LETTERED.value
    dead_lettered.attempts = 2
    dead_lettered.created_at = base_time - timedelta(hours=1)
    dead_lettered.updated_at = dead_lettered.created_at + timedelta(seconds=20)
    dead_lettered.dead_lettered_at = dead_lettered.updated_at

    hidden = jobs.create(
        job_type=report_type.name,
        job_type_id=report_type.id,
        publisher_id=first_publisher.id,
        producer_id=other_producer.id,
        queue=report_type.queue,
        payload={"request": "hidden"},
    )
    hidden.status = JobStatus.COMPLETED.value
    hidden.attempts = 100
    hidden.created_at = base_time
    hidden.completed_at = base_time + timedelta(seconds=100)

    key = issue_producer_key(
        session,
        user_id=producer.id,
        name="Dashboard reader",
        expires_at=base_time + timedelta(days=365),
    )
    no_read_key = issue_producer_key(
        session,
        user_id=producer.id,
        name="Submit only",
        expires_at=base_time + timedelta(days=365),
    )
    no_read_key.credential.scopes = ["jobs:submit"]
    session.flush()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield ProducerDashboardContext(
            session=session,
            producer=producer,
            publisher_only=publisher_only,
            first_publisher_id=first_publisher.id,
            second_publisher_id=second_publisher.id,
            jobs=(completed, running, dead_lettered),
            api_key=key.raw_key,
            no_read_api_key=no_read_key.raw_key,
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


def test_producer_job_list_supports_scoped_api_keys_filters_and_pagination(
    producer_dashboard_context,
):
    context = producer_dashboard_context

    async def scenario():
        headers = {"Authorization": f"Bearer {context.api_key}"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
        ) as client:
            first = await client.get("/producer/jobs", params={"limit": 2})
            assert first.status_code == 200
            first_body = first.json()
            assert [item["job_id"] for item in first_body["items"]] == [
                context.jobs[2].id,
                context.jobs[1].id,
            ]
            assert first_body["next_cursor"]
            assert all(
                item["producer_id"] == context.producer.id
                for item in first_body["items"]
            )

            second = await client.get(
                "/producer/jobs",
                params={"limit": 2, "cursor": first_body["next_cursor"]},
            )
            assert [item["job_id"] for item in second.json()["items"]] == [
                context.jobs[0].id
            ]

            by_publisher = await client.get(
                "/producer/jobs",
                params={"publisher_id": context.second_publisher_id},
            )
            assert [item["job_id"] for item in by_publisher.json()["items"]] == [
                context.jobs[1].id
            ]

            detail = await client.get(f"/jobs/{context.jobs[0].id}")
            assert detail.status_code == 200
            assert detail.json()["payload"] == {"request": "completed"}
            assert "attempt_history" in detail.json()

    asyncio.run(scenario())


def test_producer_analytics_are_exact_and_isolated(producer_dashboard_context):
    context = producer_dashboard_context

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, context.producer)
            response = await client.get("/producer/analytics")
            assert response.status_code == 200
            body = response.json()
            assert body["total_jobs"] == 3
            assert body["total_attempts"] == 4
            assert body["average_attempts"] == pytest.approx(4 / 3)
            assert body["terminal_jobs"] == 2
            assert body["terminal_success_rate"] == 0.5
            assert body["average_completion_latency_ms"] == 5_000.0
            assert body["status_counts"]["COMPLETED"] == 1
            assert body["status_counts"]["RUNNING"] == 1
            assert body["status_counts"]["DEAD_LETTERED"] == 1
            assert {item["publisher_id"] for item in body["job_types"]} == {
                context.first_publisher_id,
                context.second_publisher_id,
            }

            first_publisher = await client.get(
                "/producer/analytics",
                params={"publisher_id": context.first_publisher_id},
            )
            assert first_publisher.json()["total_jobs"] == 2
            assert first_publisher.json()["total_attempts"] == 3

    asyncio.run(scenario())


def test_producer_dashboard_enforces_role_and_api_key_scope(
    producer_dashboard_context,
):
    context = producer_dashboard_context

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as anonymous:
            assert (await anonymous.get("/producer/jobs")).status_code == 401

        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as publisher_client:
            await login(publisher_client, context.publisher_only)
            forbidden = await publisher_client.get("/producer/jobs")
            assert forbidden.status_code == 403
            assert forbidden.json()["error"]["code"] == "PRODUCER_ROLE_REQUIRED"

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {context.no_read_api_key}"},
        ) as limited_client:
            insufficient = await limited_client.get("/producer/analytics")
            assert insufficient.status_code == 403
            assert insufficient.json()["error"]["code"] == "INSUFFICIENT_SCOPE"

    asyncio.run(scenario())
