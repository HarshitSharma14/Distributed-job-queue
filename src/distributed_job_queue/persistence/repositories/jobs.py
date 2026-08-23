"""Persistence operations for jobs and job attempts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from distributed_job_queue.domain.job import JobStatus, transition_job
from distributed_job_queue.persistence.models import Job, JobAttempt


class JobRepository:
    """Provides database operations for the job lifecycle."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        job_type: str,
        queue: str,
        payload: dict[str, Any],
        priority: int = 0,
        max_attempts: int = 5,
        available_at: datetime | None = None,
    ) -> Job:
        job = Job(
            type=job_type,
            queue=queue,
            payload=payload,
            priority=priority,
            status=JobStatus.CREATED.value,
            max_attempts=max_attempts,
        )
        if available_at is not None:
            job.available_at = available_at
        self.session.add(job)
        self.session.flush()
        return job

    def get(self, job_id: str) -> Job | None:
        return self.session.get(Job, job_id)

    def list_by_status(self, status: JobStatus, *, limit: int = 100) -> list[Job]:
        statement = (
            select(Job)
            .where(Job.status == status.value)
            .order_by(Job.created_at)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def transition(self, job: Job, target: JobStatus) -> Job:
        current = JobStatus(job.status)
        job.status = transition_job(current, target).value
        self.session.flush()
        return job

    def record_attempt(
        self,
        job: Job,
        *,
        worker_id: str,
        status: str,
        error: dict[str, Any] | None = None,
        finished_at: datetime | None = None,
    ) -> JobAttempt:
        job.attempts += 1
        attempt = JobAttempt(
            job_id=job.id,
            worker_id=worker_id,
            attempt_number=job.attempts,
            status=status,
            error=error,
            finished_at=finished_at,
        )
        self.session.add(attempt)
        self.session.flush()
        return attempt

    def set_result(self, job: Job, result_ref: str) -> Job:
        job.result_ref = result_ref
        job.completed_at = datetime.now().astimezone()
        self.session.flush()
        return job

    def set_error(self, job: Job, error: dict[str, Any]) -> Job:
        job.error = error
        self.session.flush()
        return job
