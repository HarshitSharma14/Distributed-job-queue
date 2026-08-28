"""Human login, logout, and identity endpoints."""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from distributed_job_queue.api.auth_dependencies import (
    require_csrf,
    require_current_principal,
)
from distributed_job_queue.api.auth_schemas import CurrentUserResponse, LoginRequest
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.auth.security import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from distributed_job_queue.auth.service import AuthenticatedPrincipal, login
from distributed_job_queue.common.config import load_settings
from distributed_job_queue.persistence.repositories import AuthRepository

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
