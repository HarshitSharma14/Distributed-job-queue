"""Global PostgreSQL queries for the Admin dashboard."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.domain.worker import WorkerStatus
from distributed_job_queue.persistence.models import Job, Worker


@dataclass(frozen=True, slots=True)
class AdminWorkerCursor:
    registered_at: datetime
    worker_id: str


@dataclass(frozen=True, slots=True)
class AdminWorkerFilters:
    status: WorkerStatus | None = None
    owner_user_id: str | None = None
    capability: str | None = None


@dataclass(frozen=True, slots=True)
class AdminWorkerRow:
    worker: Worker
    active_jobs: int


class AdminDashboardRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_workers(
        self,
        *,
        filters: AdminWorkerFilters,
        limit: int,
        cursor: AdminWorkerCursor | None,
    ) -> list[AdminWorkerRow]:
        active_jobs = (
            select(Job.worker_id, func.count().label("active_jobs"))
            .where(Job.status == JobStatus.RUNNING.value)
            .group_by(Job.worker_id)
            .subquery()
        )
        conditions = []
        if filters.status is not None:
            conditions.append(Worker.status == filters.status.value)
        if filters.owner_user_id is not None:
            conditions.append(Worker.owner_user_id == filters.owner_user_id)
        if filters.capability is not None:
            conditions.append(Worker.capabilities.contains([filters.capability]))
        if cursor is not None:
            conditions.append(
                or_(
                    Worker.registered_at < cursor.registered_at,
                    and_(
                        Worker.registered_at == cursor.registered_at,
                        Worker.id < cursor.worker_id,
                    ),
                )
            )
        statement = (
            select(Worker, func.coalesce(active_jobs.c.active_jobs, 0))
            .outerjoin(active_jobs, active_jobs.c.worker_id == Worker.id)
            .where(*conditions)
            .order_by(Worker.registered_at.desc(), Worker.id.desc())
            .limit(limit + 1)
        )
        return [
            AdminWorkerRow(worker=worker, active_jobs=int(count))
            for worker, count in self.session.execute(statement)
        ]

    def queue_status_rows(self) -> list[tuple[str, str, int, datetime]]:
        statement = (
            select(Job.queue, Job.status, func.count(), func.min(Job.created_at))
            .group_by(Job.queue, Job.status)
            .order_by(Job.queue, Job.status)
        )
        return [
            (queue, status, int(count), oldest)
            for queue, status, count, oldest in self.session.execute(statement)
        ]
