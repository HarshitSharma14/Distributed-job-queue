"""Application operations exposed through the HTTP API."""

from sqlalchemy.orm import Session

from distributed_job_queue.api.schemas import JobCreateRequest, JobCreateResponse
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
