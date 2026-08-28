import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from distributed_job_queue.api.app import app
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.auth.security import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    hash_password,
    token_hash,
)
from distributed_job_queue.domain.identity import UserRole, UserStatus
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import BrowserSession, ProducerCredential
from distributed_job_queue.persistence.repositories import IdentityRepository


@pytest.fixture
def auth_context():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    identities = IdentityRepository(session)
    user = identities.create_user(
        email=f"dashboard-{uuid4()}@example.com",
        display_name="Dashboard User",
        password_hash=hash_password("correct-horse-battery-staple"),
    )
    identities.assign_role(user, UserRole.PUBLISHER)
    identities.assign_role(user, UserRole.PRODUCER)

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield session, user
    finally:
        app.dependency_overrides.clear()
        session.close()
        transaction.rollback()
        connection.close()


def run(coroutine):
    return asyncio.run(coroutine)


def test_login_identity_csrf_logout_and_revocation(auth_context):
    session, user = auth_context

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            login_response = await client.post(
                "/auth/login",
                json={
                    "email": user.email.upper(),
                    "password": "correct-horse-battery-staple",
                },
            )
            assert login_response.status_code == 200
            assert login_response.json() == {
                "user_id": user.id,
                "email": user.email,
                "display_name": "Dashboard User",
                "roles": ["PRODUCER", "PUBLISHER"],
            }
            raw_session_token = client.cookies.get(SESSION_COOKIE_NAME)
            csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
            assert raw_session_token
            assert csrf_token
            assert "HttpOnly" in login_response.headers["set-cookie"]

            stored_session = session.scalar(select(BrowserSession))
            assert stored_session is not None
            assert stored_session.token_hash == token_hash(raw_session_token)
            assert stored_session.token_hash != raw_session_token

            me_response = await client.get("/auth/me")
            assert me_response.status_code == 200
            assert me_response.json()["user_id"] == user.id

            created_key = await client.post(
                "/auth/api-keys",
                headers={CSRF_HEADER_NAME: csrf_token},
                json={"name": "Local producer", "expires_in_days": 30},
            )
            assert created_key.status_code == 200
            key_body = created_key.json()
            assert key_body["key"].startswith("djq_prod_")
            assert key_body["scopes"] == ["jobs:read-own", "jobs:submit"]
            stored_key = session.scalar(select(ProducerCredential))
            assert stored_key is not None
            assert stored_key.key_hash == token_hash(key_body["key"])
            assert stored_key.key_hash != key_body["key"]

            listed_keys = await client.get("/auth/api-keys")
            assert listed_keys.status_code == 200
            assert listed_keys.json()[0]["credential_id"] == key_body["credential_id"]
            assert "key" not in listed_keys.json()[0]

            api_key_headers = {"Authorization": f"Bearer {key_body['key']}"}
            authenticated_key = await client.get(
                f"/jobs/{uuid4()}", headers=api_key_headers
            )
            assert authenticated_key.status_code == 404

            revoked_key = await client.delete(
                f"/auth/api-keys/{key_body['credential_id']}",
                headers={CSRF_HEADER_NAME: csrf_token},
            )
            assert revoked_key.status_code == 204
            rejected_key = await client.get(
                f"/jobs/{uuid4()}", headers=api_key_headers
            )
            assert rejected_key.status_code == 401

            rejected_logout = await client.post("/auth/logout")
            assert rejected_logout.status_code == 403
            assert rejected_logout.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"

            logout_response = await client.post(
                "/auth/logout", headers={CSRF_HEADER_NAME: csrf_token}
            )
            assert logout_response.status_code == 204
            assert stored_session.revoked_at is not None

            me_after_logout = await client.get("/auth/me")
            assert me_after_logout.status_code == 401

    run(scenario())


def test_login_rejects_invalid_credentials_without_revealing_account_state(auth_context):
    _, user = auth_context

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            wrong_password = await client.post(
                "/auth/login",
                json={"email": user.email, "password": "not-the-password"},
            )
            unknown_user = await client.post(
                "/auth/login",
                json={
                    "email": "unknown@example.com",
                    "password": "not-the-password",
                },
            )
            assert wrong_password.status_code == 401
            assert unknown_user.status_code == 401
            assert wrong_password.json()["error"]["message"] == "Invalid email or password"
            assert unknown_user.json()["error"]["message"] == "Invalid email or password"

    run(scenario())


def test_disabled_user_cannot_login(auth_context):
    session, user = auth_context
    user.status = UserStatus.DISABLED.value
    session.flush()

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/auth/login",
                json={
                    "email": user.email,
                    "password": "correct-horse-battery-staple",
                },
            )
            assert response.status_code == 401

    run(scenario())
