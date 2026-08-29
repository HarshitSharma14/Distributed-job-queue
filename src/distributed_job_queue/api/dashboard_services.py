"""Shared ownership-scoped dashboard application services."""

import base64
import binascii
import json
from datetime import datetime

from sqlalchemy.orm import Session

from distributed_job_queue.api.dashboard_schemas import (
    DashboardAnalyticsResponse,
    DashboardJobListResponse,
    DashboardJobSummary,
    DashboardJobTypeAnalytics,
)
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.models import Job
from distributed_job_queue.persistence.repositories.dashboard import (
    DashboardJobFilters,
    DashboardOwner,
    DashboardRepository,
    JobCursor,
)


class InvalidDashboardFilter(ValueError):
    """Raised when a dashboard filter or cursor is invalid."""


def list_dashboard_jobs(
    session: Session,
    *,
    owner: DashboardOwner,
    owner_id: str,
    filters: DashboardJobFilters,
    limit: int,
    cursor: str | None,
) -> DashboardJobListResponse:
    _validate_filters(filters)
    decoded_cursor = _decode_cursor(cursor) if cursor else None
    jobs = DashboardRepository(session).list_jobs(
        owner=owner,
        owner_id=owner_id,
        filters=filters,
        limit=limit,
        cursor=decoded_cursor,
    )
    has_more = len(jobs) > limit
    page = jobs[:limit]
    next_cursor = _encode_cursor(page[-1]) if has_more and page else None
    return DashboardJobListResponse(
        items=[_summary(job) for job in page],
        next_cursor=next_cursor,
    )


def get_dashboard_analytics(
    session: Session,
    *,
    owner: DashboardOwner,
    owner_id: str,
    filters: DashboardJobFilters,
) -> DashboardAnalyticsResponse:
    _validate_filters(filters)
    analytics = DashboardRepository(session).analytics(
        owner=owner,
        owner_id=owner_id,
        filters=filters,
    )
    status_counts = {
        status.value: analytics.status_counts.get(status.value, 0)
        for status in JobStatus
    }
    terminal_jobs = sum(
        status_counts[status.value]
        for status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.DEAD_LETTERED)
    )
    grouped: dict[tuple[str, str, str, int], dict[str, int]] = {}
    for (
        job_type_id,
        publisher_id,
        name,
        version,
        status,
        count,
    ) in analytics.job_type_status_counts:
        grouped.setdefault(
            (job_type_id, publisher_id, name, version),
            {job_status.value: 0 for job_status in JobStatus},
        )[status] = count
    return DashboardAnalyticsResponse(
        total_jobs=analytics.total_jobs,
        total_attempts=analytics.total_attempts,
        average_attempts=(
            analytics.total_attempts / analytics.total_jobs
            if analytics.total_jobs
            else None
        ),
        terminal_jobs=terminal_jobs,
        terminal_success_rate=(
            status_counts[JobStatus.COMPLETED.value] / terminal_jobs
            if terminal_jobs
            else None
        ),
        average_completion_latency_ms=analytics.average_completion_latency_ms,
        status_counts=status_counts,
        job_types=[
            DashboardJobTypeAnalytics(
                job_type_id=job_type_id,
                publisher_id=publisher_id,
                name=name,
                version=version,
                total_jobs=sum(counts.values()),
                status_counts=counts,
            )
            for (job_type_id, publisher_id, name, version), counts in grouped.items()
        ],
    )


def _validate_filters(filters: DashboardJobFilters) -> None:
    for value in (filters.created_after, filters.created_before):
        if value is not None and value.tzinfo is None:
            raise InvalidDashboardFilter("Creation timestamps must include a timezone")
    if (
        filters.created_after is not None
        and filters.created_before is not None
        and filters.created_after >= filters.created_before
    ):
        raise InvalidDashboardFilter("created_after must be earlier than created_before")


def _encode_cursor(job: Job) -> str:
    raw = json.dumps(
        {"created_at": job.created_at.isoformat(), "job_id": job.id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> JobCursor:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(value + padding))
        created_at = datetime.fromisoformat(decoded["created_at"])
        job_id = decoded["job_id"]
        if created_at.tzinfo is None or not isinstance(job_id, str) or not job_id:
            raise ValueError
        return JobCursor(created_at=created_at, job_id=job_id)
    except (ValueError, TypeError, KeyError, binascii.Error) as exc:
        raise InvalidDashboardFilter("Cursor is invalid") from exc


def _summary(job: Job) -> DashboardJobSummary:
    return DashboardJobSummary(
        job_id=job.id,
        job_type_id=job.job_type_id,
        publisher_id=job.publisher_id,
        producer_id=job.producer_id,
        type=job.type,
        queue=job.queue,
        priority=job.priority,
        status=job.status,
        attempt_count=job.attempts,
        max_attempts=job.max_attempts,
        worker_id=job.worker_id,
        result_ref=job.result_ref,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        dead_lettered_at=job.dead_lettered_at,
    )
