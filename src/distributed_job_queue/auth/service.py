"""Human login and browser-session operations."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from sqlalchemy.orm import Session

from distributed_job_queue.auth.security import (
    new_opaque_token,
    token_hash,
    verify_password,
)
from distributed_job_queue.domain.identity import UserRole, UserStatus
from distributed_job_queue.persistence.models import (
    BrowserSession,
    ProducerCredential,
    User,
)
from distributed_job_queue.persistence.repositories import AuthRepository


PRODUCER_KEY_PREFIX = "djq_prod_"
PRODUCER_DEFAULT_SCOPES = frozenset({"jobs:submit", "jobs:read-own"})


class CredentialKind(StrEnum):
    BROWSER_SESSION = "BROWSER_SESSION"
    PRODUCER_API_KEY = "PRODUCER_API_KEY"


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    user_id: str
    email: str
    display_name: str
    roles: frozenset[UserRole]
    credential_kind: CredentialKind
    browser_session: BrowserSession | None = None
    producer_credential: ProducerCredential | None = None

    @property
    def scopes(self) -> frozenset[str]:
        if self.producer_credential is None:
            return frozenset()
        return frozenset(self.producer_credential.scopes)


@dataclass(frozen=True, slots=True)
class LoginResult:
    principal: AuthenticatedPrincipal
    session_token: str
    csrf_token: str


@dataclass(frozen=True, slots=True)
class ProducerKeyResult:
    credential: ProducerCredential
    raw_key: str


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


def issue_producer_key(
    session: Session,
    *,
    user_id: str,
    name: str,
    expires_at: datetime,
) -> ProducerKeyResult:
    raw_key = f"{PRODUCER_KEY_PREFIX}{new_opaque_token()}"
    credential = AuthRepository(session).create_producer_credential(
        user_id=user_id,
        name=name,
        key_prefix=raw_key[:16],
        key_hash=token_hash(raw_key),
        scopes=sorted(PRODUCER_DEFAULT_SCOPES),
        expires_at=expires_at,
    )
    return ProducerKeyResult(credential=credential, raw_key=raw_key)


def authenticate_producer_key(
    session: Session, raw_key: str, *, now: datetime | None = None
) -> AuthenticatedPrincipal | None:
    if not raw_key.startswith(PRODUCER_KEY_PREFIX):
        return None
    current_time = now or datetime.now(timezone.utc)
    credential = AuthRepository(session).get_active_producer_credential(
        token_hash(raw_key), now=current_time
    )
    if (
        credential is None
        or credential.user.status != UserStatus.ACTIVE.value
        or UserRole.PRODUCER.value
        not in {assignment.role for assignment in credential.user.roles}
    ):
        return None
    credential.last_used_at = current_time
    session.flush()
    return _principal(credential.user, producer_credential=credential)


def _principal(
    user: User,
    browser_session: BrowserSession | None = None,
    producer_credential: ProducerCredential | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        roles=frozenset(UserRole(assignment.role) for assignment in user.roles),
        credential_kind=(
            CredentialKind.PRODUCER_API_KEY
            if producer_credential is not None
            else CredentialKind.BROWSER_SESSION
        ),
        browser_session=browser_session,
        producer_credential=producer_credential,
    )
