"""Application operations exposed through the HTTP API."""

from sqlalchemy.orm import Session

from distributed_job_queue.api.schemas import (
    JobAttemptResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobDetailResponse,
)
from distributed_job_queue.common.config import load_settings
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.repositories import JobRepository


def submit_job(session: Session, request: JobCreateRequest) -> JobCreateResponse:
    """Create a durable job and its publication event in one transaction."""

    settings = load_settings()
    job = JobRepository(session).create(
        job_type=request.type,
        queue=request.queue,
        payload=request.payload,
        priority=request.priority,
        max_attempts=request.max_attempts or settings.max_attempts,
    )
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
