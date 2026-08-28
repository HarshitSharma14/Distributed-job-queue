"""Human login and browser-session operations."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from distributed_job_queue.auth.security import (
    new_opaque_token,
    token_hash,
    verify_password,
)
from distributed_job_queue.domain.identity import UserRole, UserStatus
from distributed_job_queue.persistence.models import BrowserSession, User
from distributed_job_queue.persistence.repositories import AuthRepository


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    user_id: str
    email: str
    display_name: str
    roles: frozenset[UserRole]
    browser_session: BrowserSession


@dataclass(frozen=True, slots=True)
class LoginResult:
    principal: AuthenticatedPrincipal
    session_token: str
    csrf_token: str


def login(
    session: Session,
    *,
    email: str,
    password: str,
    session_hours: int,
    now: datetime | None = None,
) -> LoginResult | None:
    repository = AuthRepository(session)
    user = repository.get_user_by_email(email)
    password_hash = user.password_hash if user is not None else None
    if not verify_password(password_hash, password):
        return None
    if user is None or user.status != UserStatus.ACTIVE.value:
        return None

    current_time = now or datetime.now(timezone.utc)
    session_token = new_opaque_token()
    csrf_token = new_opaque_token()
    browser_session = repository.create_session(
        user_id=user.id,
        token_hash=token_hash(session_token),
        csrf_token_hash=token_hash(csrf_token),
        expires_at=current_time + timedelta(hours=session_hours),
    )
    return LoginResult(
        principal=_principal(user, browser_session),
        session_token=session_token,
        csrf_token=csrf_token,
    )


def authenticate_session(
    session: Session, raw_token: str, *, now: datetime | None = None
) -> AuthenticatedPrincipal | None:
    current_time = now or datetime.now(timezone.utc)
    browser_session = AuthRepository(session).get_active_session(
        token_hash(raw_token), now=current_time
    )
    if (
        browser_session is None
        or browser_session.user.status != UserStatus.ACTIVE.value
    ):
        return None
    return _principal(browser_session.user, browser_session)


def _principal(user: User, browser_session: BrowserSession) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        roles=frozenset(UserRole(assignment.role) for assignment in user.roles),
        browser_session=browser_session,
    )
