import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from distributed_job_queue.api.app import app
from distributed_job_queue.api.dependencies import get_session, get_session_factory
from distributed_job_queue.auth.security import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, hash_password, token_hash
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import WorkerCredential, WorkerEnrollment
from distributed_job_queue.persistence.repositories import IdentityRepository


@pytest.fixture
def worker_management_context():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    request_session_factory = sessionmaker(
        bind=connection,
        class_=Session,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    identities = IdentityRepository(session)
    worker_user = identities.create_user(
        email=f"worker-owner-{uuid4()}@example.com",
        display_name="Worker Owner",
        password_hash=hash_password("correct-horse-battery-staple"),
    )
    identities.assign_role(worker_user, UserRole.WORKER)
    job_type = identities.create_job_type(
        publisher_id=worker_user.id,
        name="generate_report",
        queue="reports",
        handler_ref="verified/generate-report.zip",
        handler_digest="a" * 64,
        handler_signing_key_id="test-key",
        handler_release_signature="test-signature",
    )

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_session_factory] = lambda: request_session_factory
    try:
        yield session, worker_user, job_type
    finally:
        app.dependency_overrides.clear()
        session.close()
        transaction.rollback()
        connection.close()


def test_worker_enrollment_exchange_listing_and_revocation(worker_management_context):
    session, worker_user, job_type = worker_management_context

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            login = await client.post(
                "/auth/login",
                json={
                    "email": worker_user.email,
                    "password": "correct-horse-battery-staple",
                },
            )
            assert login.status_code == 200
            csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
            assert csrf_token

            created = await client.post(
                "/worker-management/enrollments",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={"job_type_id": job_type.id, "expires_in_minutes": 10},
            )
            assert created.status_code == 201
            enrollment_body = created.json()
            enrollment_token = enrollment_body["token"]
            assert enrollment_token.startswith("djq_enroll_")
            stored_enrollment = session.scalar(
                select(WorkerEnrollment).where(
                    WorkerEnrollment.id == enrollment_body["enrollment_id"]
                )
            )
            assert stored_enrollment is not None
            assert stored_enrollment.token_hash == token_hash(enrollment_token)
            assert stored_enrollment.token_hash != enrollment_token

            registered = await client.post(
                "/worker/v1/workers/register",
                headers={"Authorization": f"Bearer {enrollment_token}"},
                json={"worker_id": "external-worker-1"},
            )
            assert registered.status_code == 201
            registration = registered.json()
            agent_token = registration["worker_token"]
            assert registration["capabilities"] == ["generate_report"]
            assert registration["queue"] == "reports"
            assert agent_token.startswith("djq_worker_")

            replayed_enrollment = await client.post(
                "/worker/v1/workers/register",
                headers={"Authorization": f"Bearer {enrollment_token}"},
                json={"worker_id": "external-worker-2"},
            )
            assert replayed_enrollment.status_code == 401

            heartbeat = await client.post(
                "/worker/v1/workers/external-worker-1/heartbeat",
                headers={"Authorization": f"Bearer {agent_token}"},
            )
            assert heartbeat.status_code == 200

            agents = await client.get("/worker-management/agents")
            assert agents.status_code == 200
            assert agents.json()[0]["worker_id"] == "external-worker-1"
            assert agents.json()[0]["credential_prefix"] == agent_token[:20]

            revoked = await client.delete(
                "/worker-management/agents/external-worker-1/credential",
                headers={CSRF_HEADER_NAME: csrf_token},
            )
            assert revoked.status_code == 204
            rejected = await client.post(
                "/worker/v1/workers/external-worker-1/heartbeat",
                headers={"Authorization": f"Bearer {agent_token}"},
            )
            assert rejected.status_code == 401
            assert rejected.json()["error"]["code"] == "WORKER_UNAUTHORIZED"

            credential = session.scalar(
                select(WorkerCredential).where(
                    WorkerCredential.worker_id == "external-worker-1"
                )
            )
            assert credential is not None
            assert credential.revoked_at is not None

    asyncio.run(scenario())
