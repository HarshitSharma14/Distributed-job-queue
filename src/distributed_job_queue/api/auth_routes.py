"""Human login, logout, and identity endpoints."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from distributed_job_queue.api.auth_dependencies import (
    require_csrf,
    require_current_principal,
)
from distributed_job_queue.api.auth_schemas import (
    CurrentUserResponse,
    LoginRequest,
    ProducerKeyCreateRequest,
    ProducerKeyCreatedResponse,
    ProducerKeyResponse,
)
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.auth.security import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from distributed_job_queue.auth.service import (
    AuthenticatedPrincipal,
    issue_producer_key,
    login,
)
from distributed_job_queue.common.config import load_settings
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.persistence.repositories import AuthRepository
from distributed_job_queue.persistence.models import ProducerCredential

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger(__name__)


@router.post("/login", response_model=CurrentUserResponse)
def login_user(
    request: LoginRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> CurrentUserResponse:
    settings = load_settings()
    result = login(
        session,
        email=request.email,
        password=request.password,
        session_hours=settings.auth_session_hours,
    )
    if result is None:
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_CREDENTIALS",
            message="Invalid email or password",
        )

    max_age = settings.auth_session_hours * 60 * 60
    response.set_cookie(
        SESSION_COOKIE_NAME,
        result.session_token,
        max_age=max_age,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        result.csrf_token,
        max_age=max_age,
        secure=settings.auth_cookie_secure,
        httponly=False,
        samesite="lax",
        path="/",
    )
    logger.info(
        "User logged in",
        extra={"event": "auth.login_succeeded", "user_id": result.principal.user_id},
    )
    return _current_user_response(result.principal)


@router.get("/me", response_model=CurrentUserResponse)
def current_user(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_current_principal)
    ],
) -> CurrentUserResponse:
    return _current_user_response(principal)


@router.post("/api-keys", response_model=ProducerKeyCreatedResponse)
def create_producer_key(
    request: ProducerKeyCreateRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_csrf)],
    session: Annotated[Session, Depends(get_session)],
) -> ProducerKeyCreatedResponse:
    _require_producer(principal)
    expires_at = datetime.now(timezone.utc) + timedelta(days=request.expires_in_days)
    result = issue_producer_key(
        session,
        user_id=principal.user_id,
        name=request.name,
        expires_at=expires_at,
    )
    credential = result.credential
    return ProducerKeyCreatedResponse(
        credential_id=credential.id,
        name=credential.name,
        key=result.raw_key,
        key_prefix=credential.key_prefix,
        scopes=credential.scopes,
        created_at=credential.created_at,
        expires_at=credential.expires_at,
    )


@router.get("/api-keys", response_model=list[ProducerKeyResponse])
def list_producer_keys(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_current_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
) -> list[ProducerKeyResponse]:
    _require_producer(principal)
    credentials = AuthRepository(session).list_producer_credentials(principal.user_id)
    return [_producer_key_response(credential) for credential in credentials]


@router.delete("/api-keys/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_producer_key(
    credential_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_csrf)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    _require_producer(principal)
    repository = AuthRepository(session)
    credential = repository.get_owned_producer_credential(
        str(credential_id), user_id=principal.user_id
    )
    if credential is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="API_KEY_NOT_FOUND",
            message="API key not found",
        )
    repository.revoke_producer_credential(
        credential, now=datetime.now(timezone.utc)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_user(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_csrf)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    AuthRepository(session).revoke_session(
        principal.browser_session, now=datetime.now(timezone.utc)
    )
    settings = load_settings()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME,
        secure=settings.auth_cookie_secure,
        httponly=False,
        samesite="lax",
        path="/",
    )
    logger.info(
        "User logged out",
        extra={"event": "auth.logout", "user_id": principal.user_id},
    )
    return response


def _current_user_response(
    principal: AuthenticatedPrincipal,
) -> CurrentUserResponse:
    return CurrentUserResponse(
        user_id=principal.user_id,
        email=principal.email,
        display_name=principal.display_name,
        roles=sorted(principal.roles, key=lambda role: role.value),
    )


def _producer_key_response(credential: ProducerCredential) -> ProducerKeyResponse:
    return ProducerKeyResponse(
        credential_id=credential.id,
        name=credential.name,
        key_prefix=credential.key_prefix,
        scopes=credential.scopes,
        created_at=credential.created_at,
        expires_at=credential.expires_at,
        revoked_at=credential.revoked_at,
        last_used_at=credential.last_used_at,
    )


def _require_producer(principal: AuthenticatedPrincipal) -> None:
    if UserRole.PRODUCER not in principal.roles:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="PRODUCER_ROLE_REQUIRED",
            message="Producer role required",
        )
