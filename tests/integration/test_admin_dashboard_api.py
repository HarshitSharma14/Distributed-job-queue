import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from distributed_job_queue.api.app import app
from distributed_job_queue.api.dependencies import get_redis_queue, get_session
from distributed_job_queue.api.dependencies import get_prometheus_client
from distributed_job_queue.auth.security import hash_password
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.domain.worker import WorkerStatus
from distributed_job_queue.common.prometheus import (
    PrometheusQueryError,
    TrendPoint,
    TrendResult,
    TrendSeries,
)
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import Job, User, Worker
from distributed_job_queue.persistence.repositories import IdentityRepository, JobRepository

PASSWORD = "correct-horse-battery-staple"


class FakeRedisQueue:
    ready = {"reports": 5, "images": 2}
    inflight = {"reports": 1, "images": 0}

    def queue_size(self, queue: str) -> int:
        return self.ready.get(queue, 0)

    def inflight_size(self, queue: str) -> int:
        return self.inflight.get(queue, 0)


class UnavailableRedisQueue:
    def queue_size(self, queue: str) -> int:
        raise ConnectionError(f"Redis unavailable for {queue}")


class FakePrometheusClient:
    def dashboard_trends(self, window: str, end: datetime) -> TrendResult:
        assert window in {"1h", "6h", "24h", "7d"}
        return TrendResult(
            start=end - timedelta(hours=1),
            end=end,
            step_seconds=60,
            series=[
                TrendSeries(
                    key="job_submission_rate",
                    unit="jobs_per_second",
                    labels={"queue": "reports"},
                    points=[TrendPoint(timestamp=end, value=0.5)],
                )
            ],
        )


class UnavailablePrometheusClient:
    def dashboard_trends(self, window: str, end: datetime) -> TrendResult:
        raise PrometheusQueryError("Prometheus unavailable")

    def inflight_size(self, queue: str) -> int:
        raise ConnectionError(f"Redis unavailable for {queue}")


@dataclass(frozen=True)
class AdminDashboardContext:
    session: Session
    admin: User
    publisher_only: User
    first_publisher_id: str
    first_producer_id: str
    worker_ids: tuple[str, str]
    jobs: tuple[Job, Job, Job, Job]


@pytest.fixture
def admin_dashboard_context():
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

    admin = user("admin-dashboard", UserRole.ADMIN)
    first_publisher = user("first-publisher", UserRole.PUBLISHER)
    second_publisher = user("second-publisher", UserRole.PUBLISHER)
    first_producer = user("first-producer", UserRole.PRODUCER)
    second_producer = user("second-producer", UserRole.PRODUCER)
    first_worker_owner = user("first-worker-owner", UserRole.WORKER)
    second_worker_owner = user("second-worker-owner", UserRole.WORKER)
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
    base_time = datetime(2026, 8, 30, 10, 0, tzinfo=timezone.utc)
    first_worker = Worker(
        id=f"admin-worker-a-{uuid4().hex}",
        owner_user_id=first_worker_owner.id,
        capabilities=[report_type.name],
        status=WorkerStatus.ONLINE.value,
        registered_at=base_time - timedelta(hours=2),
        last_heartbeat_at=base_time,
    )
    second_worker = Worker(
        id=f"admin-worker-b-{uuid4().hex}",
        owner_user_id=second_worker_owner.id,
        capabilities=[image_type.name],
        status=WorkerStatus.OFFLINE.value,
        registered_at=base_time - timedelta(hours=1),
        last_heartbeat_at=base_time - timedelta(hours=1),
    )
    session.add_all([first_worker, second_worker])
    session.flush()

    def job(
        job_type,
        producer: User,
        status: JobStatus,
        hours_ago: int,
        attempts: int,
    ) -> Job:
        created = jobs.create(
            job_type=job_type.name,
            job_type_id=job_type.id,
            publisher_id=job_type.publisher_id,
            producer_id=producer.id,
            queue=job_type.queue,
            payload={"status": status.value},
        )
        created.status = status.value
        created.attempts = attempts
        created.created_at = base_time - timedelta(hours=hours_ago)
        created.updated_at = created.created_at + timedelta(seconds=attempts)
        return created

    queued = job(report_type, first_producer, JobStatus.QUEUED, 4, 0)
    running = job(image_type, second_producer, JobStatus.RUNNING, 3, 1)
    running.worker_id = first_worker.id
    running.lease_expires_at = base_time + timedelta(minutes=1)
    dead_lettered = job(
        report_type, first_producer, JobStatus.DEAD_LETTERED, 2, 3
    )
    dead_lettered.dead_lettered_at = dead_lettered.updated_at
    dead_lettered.error = {"type": "PermanentFailure", "message": "exhausted"}
    completed = job(image_type, second_producer, JobStatus.COMPLETED, 1, 1)
    completed.completed_at = completed.created_at + timedelta(seconds=8)
    session.flush()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_redis_queue] = lambda: FakeRedisQueue()
    app.dependency_overrides[get_prometheus_client] = lambda: FakePrometheusClient()
    try:
        yield AdminDashboardContext(
            session=session,
            admin=admin,
            publisher_only=first_publisher,
            first_publisher_id=first_publisher.id,
            first_producer_id=first_producer.id,
            worker_ids=(first_worker.id, second_worker.id),
            jobs=(queued, running, dead_lettered, completed),
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


def test_admin_jobs_and_analytics_are_global_filterable_and_paginated(
    admin_dashboard_context,
):
    context = admin_dashboard_context

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, context.admin)
            first = await client.get("/admin/jobs", params={"limit": 2})
            assert first.status_code == 200
            first_body = first.json()
            assert [item["job_id"] for item in first_body["items"]] == [
                context.jobs[3].id,
                context.jobs[2].id,
            ]
            second = await client.get(
                "/admin/jobs",
                params={"limit": 2, "cursor": first_body["next_cursor"]},
            )
            assert [item["job_id"] for item in second.json()["items"]] == [
                context.jobs[1].id,
                context.jobs[0].id,
            ]

            filtered = await client.get(
                "/admin/jobs",
                params={
                    "publisher_id": context.first_publisher_id,
                    "producer_id": context.first_producer_id,
                    "queue": "reports",
                },
            )
            assert {item["job_id"] for item in filtered.json()["items"]} == {
                context.jobs[0].id,
                context.jobs[2].id,
            }

            analytics = await client.get("/admin/analytics")
            assert analytics.status_code == 200
            body = analytics.json()
            assert body["total_jobs"] == 4
            assert body["total_attempts"] == 5
            assert body["status_counts"]["QUEUED"] == 1
            assert body["status_counts"]["RUNNING"] == 1
            assert body["status_counts"]["DEAD_LETTERED"] == 1
            assert body["status_counts"]["COMPLETED"] == 1

    asyncio.run(scenario())


def test_admin_overview_combines_exact_totals_with_operational_trends(
    admin_dashboard_context,
):
    context = admin_dashboard_context

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, context.admin)
            response = await client.get("/admin/overview", params={"window": "1h"})

            assert response.status_code == 200
            body = response.json()
            assert body["exact"]["total_jobs"] == 4
            assert body["exact"]["total_attempts"] == 5
            assert body["operational"]["available"] is True
            assert body["operational"]["window"] == "1h"
            assert body["operational"]["series"] == [
                {
                    "metric": "job_submission_rate",
                    "unit": "jobs_per_second",
                    "labels": {"queue": "reports"},
                    "points": [
                        {
                            "timestamp": body["operational"]["end"],
                            "value": 0.5,
                        }
                    ],
                }
            ]

    asyncio.run(scenario())


def test_admin_overview_keeps_exact_totals_without_prometheus(
    admin_dashboard_context,
):
    context = admin_dashboard_context
    app.dependency_overrides[get_prometheus_client] = lambda: None

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, context.admin)
            response = await client.get("/admin/overview")

            assert response.status_code == 200
            body = response.json()
            assert body["exact"]["total_jobs"] == 4
            assert body["operational"]["available"] is False
            assert body["operational"]["unavailable_reason"] == "not_configured"
            assert body["operational"]["series"] == []

    asyncio.run(scenario())


def test_admin_overview_keeps_exact_totals_when_prometheus_query_fails(
    admin_dashboard_context,
):
    context = admin_dashboard_context
    app.dependency_overrides[
        get_prometheus_client
    ] = lambda: UnavailablePrometheusClient()

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, context.admin)
            response = await client.get("/admin/overview")

            assert response.status_code == 200
            body = response.json()
            assert body["exact"]["total_jobs"] == 4
            assert body["operational"]["available"] is False
            assert (
                body["operational"]["unavailable_reason"]
                == "temporarily_unavailable"
            )

    asyncio.run(scenario())


def test_admin_dead_letters_are_dedicated_and_retain_full_detail(
    admin_dashboard_context,
):
    context = admin_dashboard_context

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, context.admin)
            response = await client.get("/admin/dead-letters")
            assert response.status_code == 200
            assert [item["job_id"] for item in response.json()["items"]] == [
                context.jobs[2].id
            ]
            assert response.json()["items"][0]["status"] == "DEAD_LETTERED"
            assert "lease_token" not in response.json()["items"][0]

            detail = await client.get(f"/jobs/{context.jobs[2].id}")
            assert detail.status_code == 200
            assert detail.json()["payload"] == {"status": "DEAD_LETTERED"}
            assert detail.json()["error"]["type"] == "PermanentFailure"

    asyncio.run(scenario())


def test_admin_workers_and_queues_show_global_safe_state(admin_dashboard_context):
    context = admin_dashboard_context

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, context.admin)
            workers = await client.get("/admin/workers")
            assert workers.status_code == 200
            assert {item["worker_id"] for item in workers.json()["items"]} == set(
                context.worker_ids
            )
            online = next(
                item
                for item in workers.json()["items"]
                if item["worker_id"] == context.worker_ids[0]
            )
            assert online["active_jobs"] == 1
            assert "credential_prefix" not in online
            assert "token" not in online

            offline = await client.get(
                "/admin/workers", params={"status": "OFFLINE"}
            )
            assert [item["worker_id"] for item in offline.json()["items"]] == [
                context.worker_ids[1]
            ]

            queues = await client.get("/admin/queues")
            assert queues.status_code == 200
            body = queues.json()
            assert body["redis_available"] is True
            by_name = {item["queue"]: item for item in body["items"]}
            assert by_name["reports"]["durable_jobs"] == 2
            assert by_name["reports"]["status_counts"]["QUEUED"] == 1
            assert by_name["reports"]["redis_ready_jobs"] == 5
            assert by_name["reports"]["redis_inflight_jobs"] == 1
            assert by_name["reports"]["oldest_queued_at"]
            assert by_name["images"]["durable_jobs"] == 2

    asyncio.run(scenario())


def test_admin_dashboard_requires_admin_browser_session(admin_dashboard_context):
    context = admin_dashboard_context

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as anonymous:
            assert (await anonymous.get("/admin/jobs")).status_code == 401

        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as publisher_client:
            await login(publisher_client, context.publisher_only)
            for path in (
                "/admin/overview",
                "/admin/jobs",
                "/admin/analytics",
                "/admin/workers",
                "/admin/queues",
                "/admin/dead-letters",
            ):
                response = await publisher_client.get(path)
                assert response.status_code == 403
                assert response.json()["error"]["code"] == "ADMIN_ROLE_REQUIRED"

    asyncio.run(scenario())


def test_admin_queue_view_keeps_postgres_truth_when_redis_is_unavailable(
    admin_dashboard_context,
):
    context = admin_dashboard_context
    app.dependency_overrides[get_redis_queue] = lambda: UnavailableRedisQueue()

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, context.admin)
            response = await client.get("/admin/queues")
            assert response.status_code == 200
            body = response.json()
            assert body["redis_available"] is False
            assert {item["queue"] for item in body["items"]} == {
                "images",
                "reports",
            }
            assert all(item["redis_ready_jobs"] is None for item in body["items"])
            assert all(item["redis_inflight_jobs"] is None for item in body["items"])
            assert sum(item["durable_jobs"] for item in body["items"]) == 4

    asyncio.run(scenario())
