"""Dashboard acceptance coverage over real PostgreSQL and MinIO."""

import asyncio
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import httpx
from sqlalchemy import select, func

from tests.integration.test_auth_api import auth_context
from distributed_job_queue.api.app import app
from distributed_job_queue.auth.security import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from distributed_job_queue.auth.handler_signing import generate_signing_key_pair
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.persistence.repositories import (
    IdentityRepository,
    JobRepository,
)
from distributed_job_queue.persistence.models import (
    User,
    Job,
    OutboxEvent,
    QueueControl,
    AuditEvent,
    WorkerCredential,
)
from distributed_job_queue.api.dependencies import get_result_storage

PASSWORD = "correct-horse-battery-staple"


async def sign_in(client, email, password=PASSWORD):
    response = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    client.headers[CSRF_HEADER_NAME] = client.cookies[CSRF_COOKIE_NAME]
    return response


def test_accounts_require_password_change_and_preserve_last_admin(auth_context):
    session, admin = auth_context
    IdentityRepository(session).assign_role(admin, UserRole.ADMIN)
    # The migration includes an internal bootstrap Admin; isolate the last-human-Admin case.
    from distributed_job_queue.persistence.models import UserRoleAssignment

    for other in session.scalars(
        select(User)
        .join(UserRoleAssignment)
        .where(UserRoleAssignment.role == "ADMIN", User.id != admin.id)
    ):
        other.status = "DISABLED"
    session.flush()

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            await sign_in(client, admin.email)
            body = {
                "email": f"new-{uuid4()}@example.com",
                "display_name": "New Producer",
                "roles": ["PRODUCER"],
                "temporary_password": "temporary-pass-123",
            }
            created = await client.post("/admin/users", json=body)
            assert created.status_code == 201, created.text
            assert (
                "password_hash" not in created.text
                and "temporary-pass" not in created.text
            )
            user_id = created.json()["user_id"]
            duplicate = await client.post("/admin/users", json=body)
            assert duplicate.status_code == 409
            last = await client.put(
                f"/admin/users/{admin.id}",
                json={
                    "email": admin.email,
                    "display_name": "Admin",
                    "roles": ["PRODUCER"],
                    "status": "ACTIVE",
                },
            )
            assert last.status_code == 409
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as producer:
                login = await sign_in(
                    producer, body["email"], body["temporary_password"]
                )
                assert login.json()["password_change_required"] is True
                assert (await producer.get("/producer/jobs")).status_code == 403
                assert (
                    await producer.post("/auth/api-keys", json={"name": "blocked"})
                ).status_code == 403
                assert (
                    await producer.post(
                        "/auth/password",
                        json={
                            "current_password": body["temporary_password"],
                            "new_password": "replacement-pass-123",
                        },
                    )
                ).status_code == 204
                assert (await producer.get("/producer/jobs")).status_code == 200
                assert (await producer.get("/admin/users")).status_code == 403
                reset = await client.post(
                    f"/admin/users/{user_id}/reset-password",
                    json={"temporary_password": "another-temp-pass"},
                )
                assert reset.status_code == 204
                assert (await producer.get("/auth/me")).status_code == 401
            client.headers.pop(CSRF_HEADER_NAME)
            assert (await client.post("/admin/users", json=body)).status_code == 403

    asyncio.run(scenario())


def test_upload_review_catalog_download_replay_and_queue_controls(
    auth_context, monkeypatch
):
    session, user = auth_context
    repo = IdentityRepository(session)
    repo.assign_role(user, UserRole.ADMIN)
    repo.assign_role(user, UserRole.WORKER)
    signing = generate_signing_key_pair()
    monkeypatch.setenv("HANDLER_SIGNING_PRIVATE_KEY", signing.private_key_b64)
    monkeypatch.setenv("HANDLER_SIGNING_KEY_ID", "test-key")

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            await sign_in(client, user.email)
            created = await client.post(
                "/job-types",
                json={
                    "name": f"handler_{uuid4().hex}",
                    "queue": f"queue_{uuid4().hex}",
                },
            )
            assert created.status_code == 201, created.text
            jt = created.json()
            bundle = await client.get(f"/job-types/{jt['job_type_id']}/example.zip")
            assert bundle.status_code == 200
            invalid = await client.post(
                f"/job-types/{jt['job_type_id']}/upload",
                content=b"not a zip",
                headers={"Content-Type": "application/zip"},
            )
            assert (
                invalid.status_code == 200
                and invalid.json()["artifact_status"] == "REJECTED"
            )
            uploaded = await client.post(
                f"/job-types/{jt['job_type_id']}/upload",
                content=bundle.content,
                headers={"Content-Type": "application/zip"},
            )
            assert uploaded.status_code == 200, uploaded.text
            artifact = uploaded.json()["artifact_id"]
            review = await client.get(f"/job-types/{jt['job_type_id']}/artifacts")
            assert len(review.json()["items"]) == 2
            approved = await client.post(
                f"/job-types/{jt['job_type_id']}/handler-artifacts/{artifact}/approve"
            )
            assert approved.status_code == 200, approved.text
            catalog = await client.get("/catalog/job-types?limit=1")
            assert catalog.status_code == 200
            assert (
                "handler_ref" not in catalog.text
                and "release_signature" not in catalog.text
            )
            submitted = await client.post(
                "/jobs",
                json={
                    "job_type_id": jt["job_type_id"],
                    "payload": {"a": 1},
                    "priority": 7,
                    "max_attempts": 2,
                },
            )
            assert submitted.status_code == 202
            original = session.get(Job, submitted.json()["job_id"])
            original.status = "DEAD_LETTERED"
            original.dead_lettered_at = datetime.now(timezone.utc)
            session.flush()
            headers = {"Idempotency-Key": "replay-" + uuid4().hex}
            first = await client.post(f"/jobs/{original.id}/replay", headers=headers)
            second = await client.post(f"/jobs/{original.id}/replay", headers=headers)
            assert first.status_code == 202, first.text
            assert second.json()["job_id"] == first.json()["job_id"]
            assert second.headers["Idempotency-Replayed"] == "true"
            new = session.get(Job, first.json()["job_id"])
            assert (
                new.replay_of_job_id == original.id
                and new.replay_requested_by == user.id
            )
            assert (
                new.payload == original.payload
                and new.attempts == 0
                and original.status == "DEAD_LETTERED"
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.job_id == new.id)
                )
                == 1
            )
            pause = await client.post(f"/admin/queues/{jt['queue']}/pause")
            assert pause.json()["paused"] is True
            assert session.get(QueueControl, jt["queue"]).paused is True
            assert (
                await client.post("/jobs", json={"job_type_id": jt["job_type_id"]})
            ).status_code == 202
            assert (await client.post(f"/admin/queues/{jt['queue']}/resume")).json()[
                "paused"
            ] is False
            storage = get_result_storage()
            new.status = "COMPLETED"
            new.result_ref = f"jobs/{new.id}/attempts/1/result.json"
            storage.client.put_object(
                storage.bucket, new.result_ref, BytesIO(b'{"ok":true}'), 11
            )
            session.flush()
            result = await client.get(f"/jobs/{new.id}/result")
            assert result.status_code == 200 and result.json() == {"ok": True}
            await client.post(f"/job-types/{jt['job_type_id']}/disable")
            assert (
                await client.post(
                    f"/jobs/{original.id}/replay",
                    headers={"Idempotency-Key": uuid4().hex},
                )
            ).status_code == 409
            assert (await client.get("/admin/audit")).json()["items"]
            # Replaying a completed job never alters its result.
            assert (
                await client.post(
                    f"/jobs/{new.id}/replay", headers={"Idempotency-Key": uuid4().hex}
                )
            ).status_code == 409

    asyncio.run(scenario())


def test_cross_owner_controls_and_disable_revoke_credentials(auth_context):
    session, admin = auth_context
    identities = IdentityRepository(session)
    identities.assign_role(admin, UserRole.ADMIN)
    from distributed_job_queue.auth.security import hash_password

    other = identities.create_user(
        email=f"other-{uuid4()}@example.com",
        display_name="Other",
        password_hash=hash_password(PASSWORD),
    )
    identities.assign_role(other, UserRole.PRODUCER)
    job_type = identities.create_job_type(
        publisher_id=admin.id, name="example", queue="example"
    )
    job = JobRepository(session).create(
        job_type="example",
        job_type_id=job_type.id,
        publisher_id=admin.id,
        producer_id=admin.id,
        queue="example",
        payload={},
    )
    job.status = "DEAD_LETTERED"
    session.flush()

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            await sign_in(client, other.email)
            assert (await client.get(f"/jobs/{job.id}/result")).status_code == 404
            assert (
                await client.post(
                    f"/jobs/{job.id}/replay", headers={"Idempotency-Key": "no"}
                )
            ).status_code == 404
            assert (await client.post("/admin/queues/example/pause")).status_code == 403
            key = await client.post("/auth/api-keys", json={"name": "test"})
            assert key.status_code == 200
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as control:
                await sign_in(control, admin.email)
                result = await control.put(
                    f"/admin/users/{other.id}",
                    json={
                        "email": other.email,
                        "display_name": "Other",
                        "roles": ["PRODUCER"],
                        "status": "DISABLED",
                    },
                )
                assert result.status_code == 200, result.text
            assert (await client.get("/auth/me")).status_code == 401
            client.cookies.clear()
            assert (
                await client.get(
                    "/producer/jobs",
                    headers={"Authorization": f"Bearer {key.json()['key']}"},
                )
            ).status_code == 401

    asyncio.run(scenario())
