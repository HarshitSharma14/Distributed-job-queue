"""Application operations exposed through the HTTP API."""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from distributed_job_queue.api.schemas import (
    JobAttemptResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobDetailResponse,
)
from distributed_job_queue.common.config import load_settings
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.models import Job
from distributed_job_queue.persistence.repositories import JobRepository


class IdempotencyConflict(ValueError):
    """Raised when one idempotency key is reused for different work."""


@dataclass(frozen=True, slots=True)
class JobSubmission:
    response: JobCreateResponse
    replayed: bool


def submit_job(
    session: Session,
    request: JobCreateRequest,
    *,
    idempotency_key: str | None = None,
) -> JobSubmission:
    """Create a durable job and its publication event in one transaction."""

    settings = load_settings()
    max_attempts = request.max_attempts or settings.max_attempts
    request_hash = _request_hash(request, max_attempts=max_attempts)
    repository = JobRepository(session)

    if idempotency_key is not None:
        existing = repository.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return _replay(existing, request_hash=request_hash)

    if idempotency_key is None:
        job = repository.create(
            job_type=request.type,
            queue=request.queue,
            payload=request.payload,
            priority=request.priority,
            max_attempts=max_attempts,
        )
    else:
        try:
            with session.begin_nested():
                job = repository.create(
                    job_type=request.type,
                    queue=request.queue,
                    payload=request.payload,
                    priority=request.priority,
                    max_attempts=max_attempts,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
        except IntegrityError:
            existing = repository.get_by_idempotency_key(idempotency_key)
            if existing is None:
                raise
            return _replay(existing, request_hash=request_hash)

    return JobSubmission(response=_create_response(job), replayed=False)


def _request_hash(request: JobCreateRequest, *, max_attempts: int) -> str:
    canonical_request = request.model_dump(mode="json")
    canonical_request["max_attempts"] = max_attempts
    encoded = json.dumps(
        canonical_request,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _replay(job: Job, *, request_hash: str) -> JobSubmission:
    if job.request_hash != request_hash:
        raise IdempotencyConflict(
            "Idempotency-Key was already used for a different request"
        )
    return JobSubmission(response=_create_response(job), replayed=True)


def _create_response(job: Job) -> JobCreateResponse:
    return JobCreateResponse(
        job_id=job.id,
        status=JobStatus(job.status),
        type=job.type,
        queue=job.queue,
        priority=job.priority,
        created_at=job.created_at,
    )


def get_job_detail(session: Session, job_id: str) -> JobDetailResponse | None:
    """Return authoritative state and ordered execution history."""

    job = JobRepository(session).get_with_attempts(job_id)
    if job is None:
        return None
    attempts = sorted(job.attempts_history, key=lambda attempt: attempt.attempt_number)
    return JobDetailResponse(
        job_id=job.id,
        type=job.type,
        queue=job.queue,
        payload=job.payload,
        priority=job.priority,
        status=JobStatus(job.status),
        attempt_count=job.attempts,
        max_attempts=job.max_attempts,
        available_at=job.available_at,
        worker_id=job.worker_id,
        lease_expires_at=job.lease_expires_at,
        result_ref=job.result_ref,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        dead_lettered_at=job.dead_lettered_at,
        attempt_history=[
            JobAttemptResponse(
                attempt_number=attempt.attempt_number,
                worker_id=attempt.worker_id,
                status=JobStatus(attempt.status),
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
                error=attempt.error,
            )
            for attempt in attempts
        ],
    )
