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
    authenticate_session,
)


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
