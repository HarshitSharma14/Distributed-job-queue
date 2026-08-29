"""Worker enrollment and per-agent credential lifecycle."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from distributed_job_queue.auth.security import new_opaque_token, token_hash
from distributed_job_queue.domain.identity import JobTypeStatus, UserRole, UserStatus
from distributed_job_queue.persistence.models import (
    JobType,
    User,
    Worker,
    WorkerCredential,
    WorkerEnrollment,
)

WORKER_ENROLLMENT_PREFIX = "djq_enroll_"
WORKER_CREDENTIAL_PREFIX = "djq_worker_"


class WorkerEnrollmentRejected(ValueError):
    """Raised when a Job Type cannot issue a Worker enrollment."""


class WorkerRegistrationRejected(ValueError):
    """Raised when enrollment cannot register the requested Worker Agent."""


@dataclass(frozen=True, slots=True)
class WorkerEnrollmentResult:
    enrollment: WorkerEnrollment
    raw_token: str


@dataclass(frozen=True, slots=True)
class WorkerEnrollmentPrincipal:
    enrollment: WorkerEnrollment

    @property
    def owner_user_id(self) -> str:
        return self.enrollment.owner_user_id

    @property
    def job_type(self) -> JobType:
        return self.enrollment.job_type


@dataclass(frozen=True, slots=True)
class WorkerCredentialResult:
    credential: WorkerCredential
    raw_token: str


@dataclass(frozen=True, slots=True)
class WorkerAgentPrincipal:
    credential_id: str
    worker_id: str
    owner_user_id: str
    job_type_id: str
    job_type_name: str
    queue: str
    job_type_status: str
    handler_ref: str | None
    handler_digest: str | None


def issue_worker_enrollment(
    session: Session,
    *,
    owner_user_id: str,
    job_type_id: str,
    lifetime_minutes: int,
    now: datetime | None = None,
) -> WorkerEnrollmentResult:
    job_type = session.get(JobType, job_type_id)
    if (
        job_type is None
        or job_type.status != JobTypeStatus.ACTIVE.value
        or not job_type.handler_ref
    ):
        raise WorkerEnrollmentRejected(
            "Worker enrollment requires an active Job Type with a verified handler"
        )

    current_time = now or datetime.now(timezone.utc)
    raw_token = f"{WORKER_ENROLLMENT_PREFIX}{new_opaque_token()}"
    enrollment = WorkerEnrollment(
        owner_user_id=owner_user_id,
        job_type_id=job_type.id,
        token_prefix=raw_token[:20],
        token_hash=token_hash(raw_token),
        expires_at=current_time + timedelta(minutes=lifetime_minutes),
    )
    session.add(enrollment)
    session.flush()
    return WorkerEnrollmentResult(enrollment=enrollment, raw_token=raw_token)


def authenticate_worker_enrollment(
    session: Session,
    raw_token: str,
    *,
    now: datetime | None = None,
) -> WorkerEnrollmentPrincipal | None:
    if not raw_token.startswith(WORKER_ENROLLMENT_PREFIX):
        return None
    current_time = now or datetime.now(timezone.utc)
    statement = (
        select(WorkerEnrollment)
        .where(
            WorkerEnrollment.token_hash == token_hash(raw_token),
            WorkerEnrollment.expires_at > current_time,
            WorkerEnrollment.used_at.is_(None),
            WorkerEnrollment.revoked_at.is_(None),
        )
        .options(
            selectinload(WorkerEnrollment.owner).selectinload(User.roles),
            selectinload(WorkerEnrollment.job_type),
        )
        .with_for_update()
    )
    enrollment = session.scalars(statement).one_or_none()
    if enrollment is None:
        return None
    roles = {assignment.role for assignment in enrollment.owner.roles}
    if (
        enrollment.owner.status != UserStatus.ACTIVE.value
        or UserRole.WORKER.value not in roles
        or enrollment.job_type.status != JobTypeStatus.ACTIVE.value
        or not enrollment.job_type.handler_ref
    ):
        return None
    return WorkerEnrollmentPrincipal(enrollment)


def exchange_worker_enrollment(
    session: Session,
    principal: WorkerEnrollmentPrincipal,
    *,
    worker: Worker,
    lifetime_hours: int,
    now: datetime | None = None,
) -> WorkerCredentialResult:
    enrollment = principal.enrollment
    current_time = now or datetime.now(timezone.utc)
    if (
        enrollment.used_at is not None
        or enrollment.revoked_at is not None
        or enrollment.expires_at <= current_time
        or worker.owner_user_id != enrollment.owner_user_id
    ):
        raise WorkerRegistrationRejected("Worker enrollment is no longer valid")

    session.execute(
        update(WorkerCredential)
        .where(
            WorkerCredential.worker_id == worker.id,
            WorkerCredential.revoked_at.is_(None),
        )
        .values(revoked_at=current_time)
    )
    raw_token = f"{WORKER_CREDENTIAL_PREFIX}{new_opaque_token()}"
    credential = WorkerCredential(
        worker_id=worker.id,
        owner_user_id=enrollment.owner_user_id,
        enrollment_id=enrollment.id,
        token_prefix=raw_token[:20],
        token_hash=token_hash(raw_token),
        expires_at=current_time + timedelta(hours=lifetime_hours),
    )
    enrollment.used_at = current_time
    session.add(credential)
    session.flush()
    return WorkerCredentialResult(credential=credential, raw_token=raw_token)


def authenticate_worker_agent(
    session: Session,
    raw_token: str,
    *,
    now: datetime | None = None,
) -> WorkerAgentPrincipal | None:
    if not raw_token.startswith(WORKER_CREDENTIAL_PREFIX):
        return None
    current_time = now or datetime.now(timezone.utc)
    statement = (
        select(WorkerCredential)
        .where(
            WorkerCredential.token_hash == token_hash(raw_token),
            WorkerCredential.expires_at > current_time,
            WorkerCredential.revoked_at.is_(None),
        )
        .options(
            selectinload(WorkerCredential.owner).selectinload(User.roles),
            selectinload(WorkerCredential.worker),
            selectinload(WorkerCredential.enrollment).selectinload(
                WorkerEnrollment.job_type
            ),
        )
    )
    credential = session.scalars(statement).one_or_none()
    if credential is None:
        return None
    roles = {assignment.role for assignment in credential.owner.roles}
    if (
        credential.owner.status != UserStatus.ACTIVE.value
        or UserRole.WORKER.value not in roles
        or credential.worker.owner_user_id != credential.owner_user_id
    ):
        return None
    credential.last_used_at = current_time
    session.flush()
    return WorkerAgentPrincipal(
        credential_id=credential.id,
        worker_id=credential.worker_id,
        owner_user_id=credential.owner_user_id,
        job_type_id=credential.enrollment.job_type_id,
        job_type_name=credential.enrollment.job_type.name,
        queue=credential.enrollment.job_type.queue,
        job_type_status=credential.enrollment.job_type.status,
        handler_ref=credential.enrollment.job_type.handler_ref,
        handler_digest=credential.enrollment.job_type.handler_digest,
    )
