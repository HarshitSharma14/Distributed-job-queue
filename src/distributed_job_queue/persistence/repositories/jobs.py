"""Persistence operations for jobs and job attempts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from distributed_job_queue.domain.job import JobStatus, transition_job
from distributed_job_queue.persistence.models import Job, JobAttempt, OutboxEvent


class ConcurrentJobUpdate(RuntimeError):
    """Raised when a job changed before a conditional update completed."""


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
        self._add_queue_event(job)
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
        transition_job(current, target)
        statement = (
            update(Job)
            .where(Job.id == job.id, Job.status == current.value)
            .values(status=target.value)
        )
        result = self.session.execute(statement)
        if result.rowcount != 1:
            raise ConcurrentJobUpdate(f"Job {job.id} changed concurrently")
        self.session.refresh(job)
        return job

    def mark_running(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        lease_expires_at: datetime,
    ) -> Job:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.QUEUED.value)
            .values(
                status=JobStatus.RUNNING.value,
                worker_id=worker_id,
                lease_token=lease_token,
                lease_expires_at=lease_expires_at,
            )
            .returning(Job)
        )
        job = self.session.scalars(statement).one_or_none()
        if job is None:
            raise ConcurrentJobUpdate(f"Job {job_id} is no longer claimable")
        return job

    def renew_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        lease_expires_at: datetime,
    ) -> bool:
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING.value,
                Job.worker_id == worker_id,
                Job.lease_token == lease_token,
            )
            .values(lease_expires_at=lease_expires_at)
        )
        return self.session.execute(statement).rowcount == 1

    def recover_expired(self, *, now: datetime, limit: int = 100) -> list[Job]:
        statement = (
            select(Job)
            .where(
                Job.status == JobStatus.RUNNING.value,
                Job.lease_expires_at <= now,
            )
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        jobs = list(self.session.scalars(statement))
        for job in jobs:
            job.status = JobStatus.QUEUED.value
            job.worker_id = None
            job.lease_token = None
            job.lease_expires_at = None
            self._add_queue_event(job)
        self.session.flush()
        return jobs

    def reconcile_queued(self, *, limit: int = 100) -> list[Job]:
        """Create missing outbox events so Redis can be rebuilt from PostgreSQL."""

        pending_event = exists().where(
            OutboxEvent.job_id == Job.id,
            OutboxEvent.event_type == "JOB_READY",
            OutboxEvent.published_at.is_(None),
        )
        statement = (
            select(Job)
            .where(Job.status == JobStatus.QUEUED.value, ~pending_event)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        jobs = list(self.session.scalars(statement))
        for job in jobs:
            self._add_queue_event(job)
        self.session.flush()
        return jobs

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

    def _add_queue_event(self, job: Job) -> OutboxEvent:
        event = OutboxEvent(
            job_id=job.id,
            event_type="JOB_READY",
            payload={
                "job_id": job.id,
                "queue": job.queue,
                "priority": job.priority,
            },
        )
        self.session.add(event)
        self.session.flush()
        return event
