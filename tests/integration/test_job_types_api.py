import asyncio
import hashlib
import json
import base64
from dataclasses import dataclass
from io import BytesIO
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.orm import Session

from distributed_job_queue.api.app import app
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.auth.security import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, hash_password
from distributed_job_queue.auth.handler_signing import parse_trusted_public_keys, verify_release
from distributed_job_queue.common.config import load_settings
from distributed_job_queue.domain.identity import JobTypeStatus, UserRole
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import HandlerArtifact, JobType, User
from distributed_job_queue.persistence.repositories import IdentityRepository
from distributed_job_queue.storage import MinioHandlerStorage

PASSWORD = "correct-horse-battery-staple"
SIGNING_PRIVATE_KEY = Ed25519PrivateKey.generate()
SIGNING_PRIVATE_KEY_B64 = base64.b64encode(
    SIGNING_PRIVATE_KEY.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
).decode("ascii")
SIGNING_PUBLIC_KEY_B64 = base64.b64encode(
    SIGNING_PRIVATE_KEY.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
).decode("ascii")


@dataclass(frozen=True)
class JobTypeAPIContext:
    session: Session
    publisher: User
    other_publisher: User
    producer: User
    admin: User
    storage: MinioHandlerStorage


@pytest.fixture
def job_type_context(monkeypatch):
    monkeypatch.setenv("HANDLER_SIGNING_KEY_ID", "integration-key")
    monkeypatch.setenv("HANDLER_SIGNING_PRIVATE_KEY", SIGNING_PRIVATE_KEY_B64)
    monkeypatch.setenv(
        "HANDLER_TRUSTED_PUBLIC_KEYS",
        json.dumps({"integration-key": SIGNING_PUBLIC_KEY_B64}),
    )
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    identities = IdentityRepository(session)
    settings = load_settings()
    storage = MinioHandlerStorage(
        settings.minio_endpoint,
        settings.minio_access_key,
        settings.minio_secret_key,
        settings.minio_handler_bucket,
    )
    if not storage.client.bucket_exists(storage.bucket):
        storage.client.make_bucket(storage.bucket)

    def user(name: str, role: UserRole) -> User:
        created = identities.create_user(
            email=f"{name}-{uuid4()}@example.com",
            display_name=name.replace("-", " ").title(),
            password_hash=hash_password(PASSWORD),
        )
        identities.assign_role(created, role)
        return created

    publisher = user("publisher", UserRole.PUBLISHER)
    identities.assign_role(publisher, UserRole.PRODUCER)
    context = JobTypeAPIContext(
        session=session,
        publisher=publisher,
        other_publisher=user("other-publisher", UserRole.PUBLISHER),
        producer=user("producer", UserRole.PRODUCER),
        admin=user("admin", UserRole.ADMIN),
        storage=storage,
    )

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield context
    finally:
        prefix = f"publishers/{publisher.id}/"
        for item in storage.client.list_objects(
            storage.bucket, prefix=prefix, recursive=True
        ):
            storage.client.remove_object(storage.bucket, item.object_name)
        app.dependency_overrides.clear()
        session.close()
        transaction.rollback()
        connection.close()


async def login(client: httpx.AsyncClient, user: User) -> str:
    response = await client.post(
        "/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert response.status_code == 200
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token
    return csrf_token


def test_publisher_creates_lists_reads_and_disables_draft(job_type_context):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            csrf_token = await login(client, job_type_context.publisher)
            missing_csrf = await client.post(
                "/job-types", json={"name": "generate_report", "queue": "reports"}
            )
            assert missing_csrf.status_code == 403

            created = await client.post(
                "/job-types",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={"name": "generate_report", "queue": "reports"},
            )
            assert created.status_code == 201
            body = created.json()
            assert body["publisher_id"] == job_type_context.publisher.id
            assert body["status"] == "DRAFT"
            assert body["version"] == 1
            assert body["supersedes_job_type_id"] is None
            assert body["handler_ref"] is None

            duplicate = await client.post(
                "/job-types",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={"name": "generate_report", "queue": "other"},
            )
            assert duplicate.status_code == 409

            listed = await client.get("/job-types")
            assert listed.status_code == 200
            assert [item["job_type_id"] for item in listed.json()] == [
                body["job_type_id"]
            ]

            detail = await client.get(f"/job-types/{body['job_type_id']}")
            assert detail.status_code == 200

            draft_submission = await client.post(
                "/jobs",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={"job_type_id": body["job_type_id"], "payload": {}},
            )
            assert draft_submission.status_code == 404

            bundle = handler_bundle("generate_report")
            reserved = await client.post(
                f"/job-types/{body['job_type_id']}/handler-upload",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={
                    "expected_sha256": hashlib.sha256(bundle).hexdigest(),
                    "size_bytes": len(bundle),
                },
            )
            assert reserved.status_code == 201
            upload = reserved.json()
            uploaded = httpx.put(
                upload["upload_url"],
                content=bundle,
                headers={"Content-Type": "application/zip"},
            )
            assert uploaded.status_code == 200

            verified = await client.post(
                f"/job-types/{body['job_type_id']}/handler-artifacts/"
                f"{upload['artifact_id']}/verify",
                headers={CSRF_HEADER_NAME: csrf_token},
            )
            assert verified.status_code == 200
            assert verified.json()["artifact_status"] == "VERIFIED"
            assert verified.json()["job_type_status"] == "PENDING_APPROVAL"
            stored_job_type = job_type_context.session.get(
                JobType, body["job_type_id"]
            )
            stored_artifact = job_type_context.session.get(
                HandlerArtifact, upload["artifact_id"]
            )
            assert stored_job_type is not None
            assert stored_artifact is not None
            assert stored_job_type.handler_ref is None
            assert stored_artifact.verified_ref != upload["object_ref"]

            publisher_cannot_approve = await client.post(
                f"/job-types/{body['job_type_id']}/handler-artifacts/"
                f"{upload['artifact_id']}/approve",
                headers={CSRF_HEADER_NAME: csrf_token},
            )
            assert publisher_cannot_approve.status_code == 403

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as admin_client:
                admin_csrf = await login(admin_client, job_type_context.admin)
                approved = await admin_client.post(
                    f"/job-types/{body['job_type_id']}/handler-artifacts/"
                    f"{upload['artifact_id']}/approve",
                    headers={CSRF_HEADER_NAME: admin_csrf},
                )
            assert approved.status_code == 200
            approval = approved.json()
            assert approval["artifact_status"] == "APPROVED"
            assert approval["job_type_status"] == "ACTIVE"
            assert approval["approved_by_user_id"] == job_type_context.admin.id
            assert approval["signing_key_id"] == "integration-key"
            verify_release(
                parse_trusted_public_keys(
                    json.dumps({"integration-key": SIGNING_PUBLIC_KEY_B64})
                ),
                key_id=approval["signing_key_id"],
                signature_b64=approval["release_signature"],
                job_type_id=body["job_type_id"],
                job_type="generate_report",
                version=1,
                digest=stored_artifact.actual_digest,
            )
            job_type_context.session.expire_all()
            stored_job_type = job_type_context.session.get(
                JobType, body["job_type_id"]
            )
            assert stored_job_type.handler_ref == stored_artifact.verified_ref

            overwritten_upload = httpx.put(
                upload["upload_url"], content=b"changed after verification"
            )
            assert overwritten_upload.status_code == 200
            promoted = job_type_context.storage.client.get_object(
                job_type_context.storage.bucket, stored_artifact.verified_ref
            )
            try:
                assert promoted.read() == bundle
            finally:
                promoted.close()
                promoted.release_conn()

            active_submission = await client.post(
                "/jobs",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={"job_type_id": body["job_type_id"], "payload": {}},
            )
            assert active_submission.status_code == 202

            disabled = await client.post(
                f"/job-types/{body['job_type_id']}/disable",
                headers={CSRF_HEADER_NAME: csrf_token},
            )
            assert disabled.status_code == 200
            assert disabled.json()["status"] == "DISABLED"

    asyncio.run(scenario())


def test_publisher_creates_an_immutable_next_job_type_version(job_type_context):
    source = IdentityRepository(job_type_context.session).create_job_type(
        publisher_id=job_type_context.publisher.id,
        name="versioned_report",
        version=1,
        queue="reports",
        handler_ref="verified/version-1.zip",
        handler_digest="a" * 64,
        handler_signing_key_id="integration-key",
        handler_release_signature="signed-version-1",
        status=JobTypeStatus.ACTIVE,
    )

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            csrf_token = await login(client, job_type_context.publisher)
            created = await client.post(
                f"/job-types/{source.id}/versions",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={"queue": "reports-v2"},
            )
            assert created.status_code == 201
            body = created.json()
            assert body["publisher_id"] == source.publisher_id
            assert body["name"] == source.name
            assert body["version"] == 2
            assert body["queue"] == "reports-v2"
            assert body["status"] == "DRAFT"
            assert body["supersedes_job_type_id"] == source.id
            assert body["handler_ref"] is None
            assert body["handler_digest"] is None
            assert body["handler_signing_key_id"] is None
            assert body["handler_release_signature"] is None

            stale_source = await client.post(
                f"/job-types/{source.id}/versions",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={},
            )
            assert stale_source.status_code == 409
            assert stale_source.json()["error"]["code"] == "JOB_TYPE_STATE_CONFLICT"

            unreleased_source = await client.post(
                f"/job-types/{body['job_type_id']}/versions",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={},
            )
            assert unreleased_source.status_code == 409

        job_type_context.session.expire_all()
        unchanged_source = job_type_context.session.get(JobType, source.id)
        assert unchanged_source.status == JobTypeStatus.ACTIVE.value
        assert unchanged_source.handler_ref == "verified/version-1.zip"

    asyncio.run(scenario())


def test_job_type_version_creation_is_owner_scoped_and_inherits_queue(
    job_type_context,
):
    source = IdentityRepository(job_type_context.session).create_job_type(
        publisher_id=job_type_context.publisher.id,
        name="owned_version",
        queue="original-queue",
        status=JobTypeStatus.DISABLED,
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as other_client:
            other_csrf = await login(
                other_client, job_type_context.other_publisher
            )
            hidden = await other_client.post(
                f"/job-types/{source.id}/versions",
                headers={CSRF_HEADER_NAME: other_csrf},
                json={},
            )
            assert hidden.status_code == 404

        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as owner_client:
            owner_csrf = await login(owner_client, job_type_context.publisher)
            created = await owner_client.post(
                f"/job-types/{source.id}/versions",
                headers={CSRF_HEADER_NAME: owner_csrf},
                json={},
            )
            assert created.status_code == 201
            assert created.json()["queue"] == "original-queue"

    asyncio.run(scenario())


def test_digest_mismatch_rejects_artifact_without_activation(job_type_context):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            csrf_token = await login(client, job_type_context.publisher)
            created = await client.post(
                "/job-types",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={"name": "reject_handler", "queue": "reports"},
            )
            job_type_id = created.json()["job_type_id"]
            bundle = handler_bundle("reject_handler")
            reserved = await client.post(
                f"/job-types/{job_type_id}/handler-upload",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={"expected_sha256": "0" * 64, "size_bytes": len(bundle)},
            )
            upload = reserved.json()
            uploaded = httpx.put(upload["upload_url"], content=bundle)
            assert uploaded.status_code == 200

            verified = await client.post(
                f"/job-types/{job_type_id}/handler-artifacts/"
                f"{upload['artifact_id']}/verify",
                headers={CSRF_HEADER_NAME: csrf_token},
            )
            assert verified.status_code == 200
            assert verified.json()["artifact_status"] == "REJECTED"
            assert verified.json()["job_type_status"] == "DRAFT"
            assert "digest" in verified.json()["rejection_reason"]

    asyncio.run(scenario())


def test_admin_can_reject_verified_release_and_return_job_type_to_draft(
    job_type_context,
):
    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as publisher_client:
            publisher_csrf = await login(
                publisher_client, job_type_context.publisher
            )
            job_type_id, artifact_id, bundle = await create_verified_release(
                publisher_client,
                publisher_csrf,
                name="admin_rejected_handler",
            )

        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as admin_client:
            admin_csrf = await login(admin_client, job_type_context.admin)
            rejected = await admin_client.post(
                f"/job-types/{job_type_id}/handler-artifacts/{artifact_id}/reject",
                headers={CSRF_HEADER_NAME: admin_csrf},
                json={"reason": "Handler requires unsafe external access"},
            )

        assert rejected.status_code == 200
        body = rejected.json()
        assert body["artifact_status"] == "REJECTED"
        assert body["job_type_status"] == "DRAFT"
        assert body["rejected_by_user_id"] == job_type_context.admin.id
        assert body["rejected_at"]
        assert body["rejection_reason"] == "Handler requires unsafe external access"

        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as publisher_client:
            publisher_csrf = await login(
                publisher_client, job_type_context.publisher
            )
            replacement = await publisher_client.post(
                f"/job-types/{job_type_id}/handler-upload",
                headers={CSRF_HEADER_NAME: publisher_csrf},
                json={
                    "expected_sha256": hashlib.sha256(bundle).hexdigest(),
                    "size_bytes": len(bundle),
                },
            )
            assert replacement.status_code == 201

    asyncio.run(scenario())


def test_admin_approval_fails_closed_without_private_signing_key(
    job_type_context, monkeypatch
):
    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as publisher_client:
            publisher_csrf = await login(
                publisher_client, job_type_context.publisher
            )
            job_type_id, artifact_id, _ = await create_verified_release(
                publisher_client,
                publisher_csrf,
                name="unsigned_handler",
            )

        monkeypatch.delenv("HANDLER_SIGNING_PRIVATE_KEY", raising=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as admin_client:
            admin_csrf = await login(admin_client, job_type_context.admin)
            approval = await admin_client.post(
                f"/job-types/{job_type_id}/handler-artifacts/{artifact_id}/approve",
                headers={CSRF_HEADER_NAME: admin_csrf},
            )

        assert approval.status_code == 503
        assert approval.json()["error"]["code"] == "HANDLER_SIGNING_UNAVAILABLE"
        job_type = job_type_context.session.get(JobType, job_type_id)
        assert job_type.status == "PENDING_APPROVAL"
        assert job_type.handler_ref is None

    asyncio.run(scenario())


def test_publishers_are_isolated_and_admin_can_see_all(job_type_context):
    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as owner_client:
            csrf_token = await login(owner_client, job_type_context.publisher)
            created = await owner_client.post(
                "/job-types",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={"name": "resize_image", "queue": "images"},
            )
            job_type_id = created.json()["job_type_id"]

        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as other_client:
            await login(other_client, job_type_context.other_publisher)
            hidden = await other_client.get(f"/job-types/{job_type_id}")
            assert hidden.status_code == 404
            listed = await other_client.get("/job-types")
            assert listed.json() == []

        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as admin_client:
            await login(admin_client, job_type_context.admin)
            visible = await admin_client.get(f"/job-types/{job_type_id}")
            assert visible.status_code == 200

    asyncio.run(scenario())


def test_producer_without_publisher_role_cannot_manage_job_types(job_type_context):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await login(client, job_type_context.producer)
            response = await client.get("/job-types")
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "PUBLISHER_ROLE_REQUIRED"

    asyncio.run(scenario())


def handler_bundle(job_type: str) -> bytes:
    content = BytesIO()
    with ZipFile(content, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"job_type": job_type, "entrypoint": "handler:handle"}),
        )
        archive.writestr("handler.py", "def handle(payload):\n    return payload\n")
    return content.getvalue()


async def create_verified_release(
    client: httpx.AsyncClient,
    csrf_token: str,
    *,
    name: str,
) -> tuple[str, str, bytes]:
    created = await client.post(
        "/job-types",
        headers={CSRF_HEADER_NAME: csrf_token},
        json={"name": name, "queue": "reports"},
    )
    job_type_id = created.json()["job_type_id"]
    bundle = handler_bundle(name)
    reserved = await client.post(
        f"/job-types/{job_type_id}/handler-upload",
        headers={CSRF_HEADER_NAME: csrf_token},
        json={
            "expected_sha256": hashlib.sha256(bundle).hexdigest(),
            "size_bytes": len(bundle),
        },
    )
    artifact_id = reserved.json()["artifact_id"]
    assert httpx.put(reserved.json()["upload_url"], content=bundle).status_code == 200
    verified = await client.post(
        f"/job-types/{job_type_id}/handler-artifacts/{artifact_id}/verify",
        headers={CSRF_HEADER_NAME: csrf_token},
    )
    assert verified.status_code == 200
    assert verified.json()["job_type_status"] == "PENDING_APPROVAL"
    return job_type_id, artifact_id, bundle
