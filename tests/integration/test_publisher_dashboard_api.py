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
from distributed_job_queue.persistence.models import Job, User
from distributed_job_queue.persistence.repositories import IdentityRepository, JobRepository

PASSWORD = "correct-horse-battery-staple"


@dataclass(frozen=True)
class PublisherDashboardContext:
    session: Session
    publisher: User
    producer_only: User
    report_job_type_id: str
    image_job_type_id: str
    jobs: tuple[Job, Job, Job]
    base_time: datetime


@pytest.fixture
def publisher_dashboard_context():
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

    publisher = user("publisher-dashboard", UserRole.PUBLISHER)
    producer = user("dashboard-producer", UserRole.PRODUCER)
    producer_only = user("producer-only", UserRole.PRODUCER)
    other_publisher = user("other-publisher", UserRole.PUBLISHER)
    report_type = identities.create_job_type(
        publisher_id=publisher.id,
        name="generate_report",
        version=1,
        queue="reports",
    )
    image_type = identities.create_job_type(
        publisher_id=publisher.id,
        name="resize_image",
        version=1,
        queue="images",
    )
    other_type = identities.create_job_type(
        publisher_id=other_publisher.id,
        name="other_job",
        queue="other",
    )
    base_time = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)

    completed = jobs.create(
        job_type=report_type.name,
        job_type_id=report_type.id,
        publisher_id=publisher.id,
        producer_id=producer.id,
        queue=report_type.queue,
        payload={"job": "completed"},
    )
    completed.status = JobStatus.COMPLETED.value
    completed.attempts = 1
    completed.created_at = base_time - timedelta(hours=3)
    completed.updated_at = completed.created_at + timedelta(seconds=10)
    completed.completed_at = completed.updated_at

    retrying = jobs.create(
        job_type=report_type.name,
        job_type_id=report_type.id,
        publisher_id=publisher.id,
        producer_id=producer.id,
        queue=report_type.queue,
        payload={"job": "retrying"},
    )
    retrying.status = JobStatus.RETRY_WAIT.value
    retrying.attempts = 2
    retrying.created_at = base_time - timedelta(hours=2)
    retrying.updated_at = retrying.created_at + timedelta(seconds=20)
    retrying.error = {"type": "TemporaryFailure", "message": "retry later"}

    dead_lettered = jobs.create(
        job_type=image_type.name,
        job_type_id=image_type.id,
        publisher_id=publisher.id,
        producer_id=producer.id,
        queue=image_type.queue,
        payload={"job": "dead"},
    )
    dead_lettered.status = JobStatus.DEAD_LETTERED.value
    dead_lettered.attempts = 3
    dead_lettered.created_at = base_time - timedelta(hours=1)
    dead_lettered.updated_at = dead_lettered.created_at + timedelta(seconds=30)
    dead_lettered.dead_lettered_at = dead_lettered.updated_at

    hidden = jobs.create(
        job_type=other_type.name,
        job_type_id=other_type.id,
        publisher_id=other_publisher.id,
        producer_id=producer.id,
        queue=other_type.queue,
        payload={"job": "hidden"},
    )
    hidden.status = JobStatus.COMPLETED.value
    hidden.attempts = 50
    hidden.created_at = base_time
    hidden.completed_at = base_time + timedelta(seconds=50)
    session.flush()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield PublisherDashboardContext(
            session=session,
            publisher=publisher,
            producer_only=producer_only,
            report_job_type_id=report_type.id,
            image_job_type_id=image_type.id,
            jobs=(completed, retrying, dead_lettered),
            base_time=base_time,
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


def test_publisher_job_list_is_scoped_filtered_and_cursor_paginated(
    publisher_dashboard_context,
):
    context = publisher_dashboard_context

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, context.publisher)
            first = await client.get("/publisher/jobs", params={"limit": 2})
            assert first.status_code == 200
            first_body = first.json()
            assert [item["job_id"] for item in first_body["items"]] == [
                context.jobs[2].id,
                context.jobs[1].id,
            ]
            assert first_body["next_cursor"]
            assert "payload" not in first_body["items"][0]

            second = await client.get(
                "/publisher/jobs",
                params={"limit": 2, "cursor": first_body["next_cursor"]},
            )
            assert second.status_code == 200
            assert [item["job_id"] for item in second.json()["items"]] == [
                context.jobs[0].id
            ]
            assert second.json()["next_cursor"] is None

            completed = await client.get(
                "/publisher/jobs", params={"status": "COMPLETED"}
            )
            assert [item["job_id"] for item in completed.json()["items"]] == [
                context.jobs[0].id
            ]

            recent = await client.get(
                "/publisher/jobs",
                params={
                    "created_after": (
                        context.base_time - timedelta(hours=2, minutes=30)
                    ).isoformat()
                },
            )
            assert {item["job_id"] for item in recent.json()["items"]} == {
                context.jobs[1].id,
                context.jobs[2].id,
            }

            invalid_cursor = await client.get(
                "/publisher/jobs", params={"cursor": "not-a-cursor"}
            )
            assert invalid_cursor.status_code == 400
            assert (
                invalid_cursor.json()["error"]["code"]
                == "DASHBOARD_FILTER_INVALID"
            )

    asyncio.run(scenario())


def test_publisher_analytics_are_exact_scoped_and_filterable(
    publisher_dashboard_context,
):
    context = publisher_dashboard_context

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, context.publisher)
            response = await client.get("/publisher/analytics")
            assert response.status_code == 200
            body = response.json()
            assert body["total_jobs"] == 3
            assert body["total_attempts"] == 6
            assert body["average_attempts"] == 2.0
            assert body["terminal_jobs"] == 2
            assert body["terminal_success_rate"] == 0.5
            assert body["average_completion_latency_ms"] == 10_000.0
            assert body["status_counts"]["COMPLETED"] == 1
            assert body["status_counts"]["RETRY_WAIT"] == 1
            assert body["status_counts"]["DEAD_LETTERED"] == 1
            assert body["status_counts"]["RUNNING"] == 0
            assert sum(item["total_jobs"] for item in body["job_types"]) == 3

            report_only = await client.get(
                "/publisher/analytics",
                params={"job_type_id": context.report_job_type_id},
            )
            assert report_only.status_code == 200
            assert report_only.json()["total_jobs"] == 2
            assert report_only.json()["total_attempts"] == 3
            assert len(report_only.json()["job_types"]) == 1

    asyncio.run(scenario())


def test_publisher_dashboard_requires_a_publisher_browser_session(
    publisher_dashboard_context,
):
    context = publisher_dashboard_context

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as anonymous:
            unauthenticated = await anonymous.get("/publisher/jobs")
            assert unauthenticated.status_code == 401

        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as producer_client:
            await login(producer_client, context.producer_only)
            forbidden = await producer_client.get("/publisher/analytics")
            assert forbidden.status_code == 403
            assert forbidden.json()["error"]["code"] == "PUBLISHER_ROLE_REQUIRED"

    asyncio.run(scenario())
