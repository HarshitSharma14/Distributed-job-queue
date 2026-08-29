"""Exact PostgreSQL queries for ownership-scoped product dashboards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.models import Job, JobType


@dataclass(frozen=True, slots=True)
class JobCursor:
    created_at: datetime
    job_id: str


DashboardOwner = Literal["admin", "publisher", "producer"]


@dataclass(frozen=True, slots=True)
class DashboardJobFilters:
    status: JobStatus | None = None
    job_type_id: str | None = None
    publisher_id: str | None = None
    producer_id: str | None = None
    queue: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


@dataclass(frozen=True, slots=True)
class DashboardAnalytics:
    total_jobs: int
    total_attempts: int
    status_counts: dict[str, int]
    average_completion_latency_ms: float | None
    job_type_status_counts: list[tuple[str, str, str, int, str, int]]


class DashboardRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_jobs(
        self,
        *,
        owner: DashboardOwner,
        owner_id: str,
        filters: DashboardJobFilters,
        limit: int,
        cursor: JobCursor | None,
    ) -> list[Job]:
        conditions = self._conditions(owner, owner_id, filters)
        if cursor is not None:
            conditions.append(
                or_(
                    Job.created_at < cursor.created_at,
                    and_(
                        Job.created_at == cursor.created_at,
                        Job.id < cursor.job_id,
                    ),
                )
            )
        statement = (
            select(Job)
            .where(*conditions)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(limit + 1)
        )
        return list(self.session.scalars(statement))

    def analytics(
        self,
        *,
        owner: DashboardOwner,
        owner_id: str,
        filters: DashboardJobFilters,
    ) -> DashboardAnalytics:
        conditions = self._conditions(owner, owner_id, filters)
        status_rows = self.session.execute(
            select(Job.status, func.count()).where(*conditions).group_by(Job.status)
        )
        status_counts = {status: int(count) for status, count in status_rows}
        total_jobs = sum(status_counts.values())
        total_attempts = int(
            self.session.scalar(
                select(func.coalesce(func.sum(Job.attempts), 0)).where(*conditions)
            )
            or 0
        )
        average_latency = self.session.scalar(
            select(
                func.avg(
                    func.extract("epoch", Job.completed_at - Job.created_at) * 1000
                )
            ).where(*conditions, Job.completed_at.is_not(None))
        )
        breakdown = list(
            self.session.execute(
                select(
                    Job.job_type_id,
                    Job.publisher_id,
                    Job.type,
                    JobType.version,
                    Job.status,
                    func.count(),
                )
                .join(JobType, JobType.id == Job.job_type_id)
                .where(*conditions)
                .group_by(
                    Job.job_type_id,
                    Job.publisher_id,
                    Job.type,
                    JobType.version,
                    Job.status,
                )
                .order_by(Job.type, JobType.version, Job.status)
            )
        )
        return DashboardAnalytics(
            total_jobs=total_jobs,
            total_attempts=total_attempts,
            status_counts=status_counts,
            average_completion_latency_ms=(
                float(average_latency) if average_latency is not None else None
            ),
            job_type_status_counts=[
                (job_type_id, publisher_id, name, version, status, int(count))
                for job_type_id, publisher_id, name, version, status, count in breakdown
            ],
        )

    @staticmethod
    def _conditions(
        owner: DashboardOwner,
        owner_id: str,
        filters: DashboardJobFilters,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if owner == "publisher":
            conditions.append(Job.publisher_id == owner_id)
        elif owner == "producer":
            conditions.append(Job.producer_id == owner_id)
        if filters.status is not None:
            conditions.append(Job.status == filters.status.value)
        if filters.job_type_id is not None:
            conditions.append(Job.job_type_id == filters.job_type_id)
        if filters.publisher_id is not None:
            conditions.append(Job.publisher_id == filters.publisher_id)
        if filters.producer_id is not None:
            conditions.append(Job.producer_id == filters.producer_id)
        if filters.queue is not None:
            conditions.append(Job.queue == filters.queue)
        if filters.created_after is not None:
            conditions.append(Job.created_at >= filters.created_after)
        if filters.created_before is not None:
            conditions.append(Job.created_at < filters.created_before)
        return conditions
