"""PostgreSQL queries for Worker-owned assignments and attempt history."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.models import Job, JobAttempt, Worker


@dataclass(frozen=True, slots=True)
class WorkerDashboardCursor:
    occurred_at: datetime
    record_id: str


@dataclass(frozen=True, slots=True)
class WorkerAssignmentFilters:
    worker_id: str | None = None
    job_type_id: str | None = None
    queue: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerAttemptFilters:
    worker_id: str | None = None
    job_type_id: str | None = None
    status: JobStatus | None = None
    started_after: datetime | None = None
    started_before: datetime | None = None


class WorkerDashboardRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_active_assignments(
        self,
        *,
        owner_user_id: str,
        filters: WorkerAssignmentFilters,
        limit: int,
        cursor: WorkerDashboardCursor | None,
    ) -> list[tuple[Job, JobAttempt]]:
        conditions = [
            Worker.owner_user_id == owner_user_id,
            Job.status == JobStatus.RUNNING.value,
        ]
        if filters.worker_id is not None:
            conditions.append(Job.worker_id == filters.worker_id)
        if filters.job_type_id is not None:
            conditions.append(Job.job_type_id == filters.job_type_id)
        if filters.queue is not None:
            conditions.append(Job.queue == filters.queue)
        if cursor is not None:
            conditions.append(
                or_(
                    JobAttempt.started_at < cursor.occurred_at,
                    and_(
                        JobAttempt.started_at == cursor.occurred_at,
                        JobAttempt.id < cursor.record_id,
                    ),
                )
            )
        statement = (
            select(Job, JobAttempt)
            .join(Worker, Worker.id == Job.worker_id)
            .join(
                JobAttempt,
                and_(
                    JobAttempt.job_id == Job.id,
                    JobAttempt.attempt_number == Job.attempts,
                    JobAttempt.status == JobStatus.RUNNING.value,
                ),
            )
            .where(*conditions)
            .order_by(JobAttempt.started_at.desc(), JobAttempt.id.desc())
            .limit(limit + 1)
        )
        return [(job, attempt) for job, attempt in self.session.execute(statement)]

    def list_attempts(
        self,
        *,
        owner_user_id: str,
        filters: WorkerAttemptFilters,
        limit: int,
        cursor: WorkerDashboardCursor | None,
    ) -> list[tuple[JobAttempt, Job]]:
        conditions = [Worker.owner_user_id == owner_user_id]
        if filters.worker_id is not None:
            conditions.append(JobAttempt.worker_id == filters.worker_id)
        if filters.job_type_id is not None:
            conditions.append(Job.job_type_id == filters.job_type_id)
        if filters.status is not None:
            conditions.append(JobAttempt.status == filters.status.value)
        if filters.started_after is not None:
            conditions.append(JobAttempt.started_at >= filters.started_after)
        if filters.started_before is not None:
            conditions.append(JobAttempt.started_at < filters.started_before)
        if cursor is not None:
            conditions.append(
                or_(
                    JobAttempt.started_at < cursor.occurred_at,
                    and_(
                        JobAttempt.started_at == cursor.occurred_at,
                        JobAttempt.id < cursor.record_id,
                    ),
                )
            )
        statement = (
            select(JobAttempt, Job)
            .join(Worker, Worker.id == JobAttempt.worker_id)
            .join(Job, Job.id == JobAttempt.job_id)
            .where(*conditions)
            .order_by(JobAttempt.started_at.desc(), JobAttempt.id.desc())
            .limit(limit + 1)
        )
        return [(attempt, job) for attempt, job in self.session.execute(statement)]
