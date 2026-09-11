"""Transactional dashboard controls. PostgreSQL remains authoritative."""

from datetime import datetime, timezone
import hashlib

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from distributed_job_queue.api.errors import APIError
from distributed_job_queue.auth.service import AuthenticatedPrincipal
from distributed_job_queue.domain.identity import UserRole, JobTypeStatus
from distributed_job_queue.persistence.models import (
    AuditEvent,
    BrowserSession,
    ProducerCredential,
    WorkerCredential,
    WorkerEnrollment,
    QueueControl,
    Job,
    JobType,
)
from distributed_job_queue.persistence.repositories import JobRepository


def audit(
    session: Session, actor_id: str, action: str, target_id: str, **details
) -> None:
    session.add(
        AuditEvent(
            actor_id=actor_id, action=action, target_id=target_id, details=details
        )
    )


def revoke_user_access(session: Session, user_id: str) -> None:
    now = datetime.now(timezone.utc)
    for model, owner in (
        (BrowserSession, BrowserSession.user_id),
        (ProducerCredential, ProducerCredential.user_id),
        (WorkerCredential, WorkerCredential.owner_user_id),
        (WorkerEnrollment, WorkerEnrollment.owner_user_id),
    ):
        session.execute(
            update(model)
            .where(owner == user_id, model.revoked_at.is_(None))
            .values(revoked_at=now)
        )


def lock_queue(session: Session, queue: str) -> QueueControl:
    # One durable lock shared by pause/resume and the final claim handoff.
    session.execute(
        insert(QueueControl)
        .values(queue=queue, paused=False)
        .on_conflict_do_nothing(index_elements=[QueueControl.queue])
    )
    return session.scalar(
        select(QueueControl)
        .where(QueueControl.queue == queue)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def replay_dead_letter(
    session: Session, job_id: str, principal: AuthenticatedPrincipal, key: str
) -> tuple[Job, bool]:
    original = session.get(Job, job_id)
    if original is None or not (
        UserRole.ADMIN in principal.roles
        or (
            UserRole.PRODUCER in principal.roles
            and original.producer_id == principal.user_id
        )
    ):
        raise APIError(status_code=404, code="JOB_NOT_FOUND", message="Job not found")
    if original.status != "DEAD_LETTERED":
        raise APIError(
            status_code=409,
            code="REPLAY_CONFLICT",
            message="Only dead-lettered jobs can be replayed",
        )
    # Serialize requests for the same Producer/key, including requests by different Admins.
    lock = int.from_bytes(
        hashlib.sha256(f"replay:{original.producer_id}:{key}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    repo = JobRepository(session)
    fingerprint = hashlib.sha256(
        f"replay:{job_id}:{principal.user_id}".encode()
    ).hexdigest()
    existing = repo.get_by_idempotency_key(key, producer_id=original.producer_id)
    if existing:
        if existing.request_hash != fingerprint:
            raise APIError(
                status_code=409,
                code="IDEMPOTENCY_CONFLICT",
                message="Idempotency-Key was already used for a different request",
            )
        return existing, True
    job_type = session.scalar(
        select(JobType).where(JobType.id == original.job_type_id).with_for_update()
    )
    if job_type.status != JobTypeStatus.ACTIVE.value:
        raise APIError(
            status_code=409,
            code="RELEASE_INACTIVE",
            message="The original Job Type version must be active to replay",
        )
    from sqlalchemy.exc import IntegrityError

    try:
        with session.begin_nested():
            job = repo.create(
                job_type=original.type,
                job_type_id=original.job_type_id,
                publisher_id=original.publisher_id,
                producer_id=original.producer_id,
                queue=original.queue,
                payload=dict(original.payload),
                priority=original.priority,
                max_attempts=original.max_attempts,
                idempotency_key=key,
                request_hash=fingerprint,
            )
            job.replay_of_job_id = original.id
            job.replay_requested_by = principal.user_id
            session.flush()
    except IntegrityError as exc:
        raise APIError(
            status_code=409,
            code="IDEMPOTENCY_CONFLICT",
            message="Idempotency-Key was already used for a different request",
        ) from exc
    audit(session, principal.user_id, "job.replay", job.id, original_job_id=original.id)
    return job, False
