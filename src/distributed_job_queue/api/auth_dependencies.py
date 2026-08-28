"""Authentication and CSRF dependencies for dashboard requests."""

from hmac import compare_digest
from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.orm import Session

from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.auth.security import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    token_hash,
)
from distributed_job_queue.auth.service import (
    AuthenticatedPrincipal,
    CredentialKind,
    authenticate_producer_key,
    authenticate_session,
)
from distributed_job_queue.domain.identity import UserRole


def require_current_principal(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AuthenticatedPrincipal:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    principal = (
        authenticate_session(session, raw_token) if raw_token is not None else None
    )
    if principal is None:
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTHENTICATION_REQUIRED",
            message="Authentication required",
        )
    return principal


def require_csrf(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_current_principal)],
) -> AuthenticatedPrincipal:
    return _validate_csrf(request, principal)


def require_product_principal(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AuthenticatedPrincipal:
    authorization = request.headers.get("Authorization", "")
    principal: AuthenticatedPrincipal | None = None
    if authorization:
        scheme, _, raw_key = authorization.partition(" ")
        if scheme.lower() == "bearer" and raw_key:
            principal = authenticate_producer_key(session, raw_key)
    else:
        raw_token = request.cookies.get(SESSION_COOKIE_NAME)
        if raw_token:
            principal = authenticate_session(session, raw_token)
    if principal is None:
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTHENTICATION_REQUIRED",
            message="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def require_job_submission_principal(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_product_principal)],
) -> AuthenticatedPrincipal:
    if UserRole.PRODUCER not in principal.roles:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="PRODUCER_ROLE_REQUIRED",
            message="Producer role required",
        )
    if principal.credential_kind == CredentialKind.PRODUCER_API_KEY:
        if "jobs:submit" not in principal.scopes:
            raise APIError(
                status_code=status.HTTP_403_FORBIDDEN,
                code="INSUFFICIENT_SCOPE",
                message="Credential cannot submit jobs",
            )
        return principal
    return _validate_csrf(request, principal)


def require_job_read_principal(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_product_principal)],
) -> AuthenticatedPrincipal:
    allowed_roles = {UserRole.ADMIN, UserRole.PUBLISHER, UserRole.PRODUCER}
    if principal.roles.isdisjoint(allowed_roles):
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="JOB_ACCESS_FORBIDDEN",
            message="Job access is not permitted",
        )
    if (
        principal.credential_kind == CredentialKind.PRODUCER_API_KEY
        and "jobs:read-own" not in principal.scopes
    ):
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="INSUFFICIENT_SCOPE",
            message="Credential cannot read jobs",
        )
    return principal


def _validate_csrf(
    request: Request, principal: AuthenticatedPrincipal
) -> AuthenticatedPrincipal:
    if principal.browser_session is None:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="BROWSER_SESSION_REQUIRED",
            message="Browser session required",
        )
    header_token = request.headers.get(CSRF_HEADER_NAME)
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    expected_hash = principal.browser_session.csrf_token_hash
    if (
        not header_token
        or not cookie_token
        or not compare_digest(header_token, cookie_token)
        or not compare_digest(token_hash(header_token), expected_hash)
    ):
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="CSRF_VALIDATION_FAILED",
            message="CSRF validation failed",
        )
    return principal
