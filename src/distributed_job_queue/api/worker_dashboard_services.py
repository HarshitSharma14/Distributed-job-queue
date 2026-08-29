"""Worker-owned assignment and attempt-history services."""

import base64
import binascii
import json
from datetime import datetime

from sqlalchemy.orm import Session

from distributed_job_queue.api.worker_dashboard_schemas import (
    WorkerAssignmentListResponse,
    WorkerAssignmentSummary,
    WorkerAttemptListResponse,
    WorkerAttemptSummary,
)
from distributed_job_queue.persistence.models import Job, JobAttempt
from distributed_job_queue.persistence.repositories.worker_dashboard import (
    WorkerAssignmentFilters,
    WorkerAttemptFilters,
    WorkerDashboardCursor,
    WorkerDashboardRepository,
)


class InvalidWorkerDashboardFilter(ValueError):
    """Raised when Worker dashboard filters or cursors are invalid."""


def list_worker_assignments(
    session: Session,
    *,
    owner_user_id: str,
    filters: WorkerAssignmentFilters,
    limit: int,
    cursor: str | None,
) -> WorkerAssignmentListResponse:
    decoded = _decode_cursor(cursor) if cursor else None
    rows = WorkerDashboardRepository(session).list_active_assignments(
        owner_user_id=owner_user_id,
        filters=filters,
        limit=limit,
        cursor=decoded,
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    return WorkerAssignmentListResponse(
        items=[_assignment(job, attempt) for job, attempt in page],
        next_cursor=(
            _encode_cursor(page[-1][1].started_at, page[-1][1].id)
            if has_more and page
            else None
        ),
    )


def list_worker_attempts(
    session: Session,
    *,
    owner_user_id: str,
    filters: WorkerAttemptFilters,
    limit: int,
    cursor: str | None,
) -> WorkerAttemptListResponse:
    _validate_attempt_filters(filters)
    decoded = _decode_cursor(cursor) if cursor else None
    rows = WorkerDashboardRepository(session).list_attempts(
        owner_user_id=owner_user_id,
        filters=filters,
        limit=limit,
        cursor=decoded,
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    return WorkerAttemptListResponse(
        items=[_attempt(attempt, job) for attempt, job in page],
        next_cursor=(
            _encode_cursor(page[-1][0].started_at, page[-1][0].id)
            if has_more and page
            else None
        ),
    )


def _validate_attempt_filters(filters: WorkerAttemptFilters) -> None:
    for value in (filters.started_after, filters.started_before):
        if value is not None and value.tzinfo is None:
            raise InvalidWorkerDashboardFilter(
                "Attempt timestamps must include a timezone"
            )
    if (
        filters.started_after is not None
        and filters.started_before is not None
        and filters.started_after >= filters.started_before
    ):
        raise InvalidWorkerDashboardFilter(
            "started_after must be earlier than started_before"
        )


def _encode_cursor(occurred_at: datetime, record_id: str) -> str:
    raw = json.dumps(
        {"occurred_at": occurred_at.isoformat(), "record_id": record_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> WorkerDashboardCursor:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(value + padding))
        occurred_at = datetime.fromisoformat(decoded["occurred_at"])
        record_id = decoded["record_id"]
        if occurred_at.tzinfo is None or not isinstance(record_id, str) or not record_id:
            raise ValueError
        return WorkerDashboardCursor(occurred_at=occurred_at, record_id=record_id)
    except (ValueError, TypeError, KeyError, binascii.Error) as exc:
        raise InvalidWorkerDashboardFilter("Cursor is invalid") from exc


def _assignment(job: Job, attempt: JobAttempt) -> WorkerAssignmentSummary:
    return WorkerAssignmentSummary(
        job_id=job.id,
        job_type_id=job.job_type_id,
        type=job.type,
        queue=job.queue,
        priority=job.priority,
        status=job.status,
        attempt_number=job.attempts,
        max_attempts=job.max_attempts,
        worker_id=job.worker_id,
        lease_expires_at=job.lease_expires_at,
        assigned_at=attempt.started_at,
    )


def _attempt(attempt: JobAttempt, job: Job) -> WorkerAttemptSummary:
    duration_ms = (
        (attempt.finished_at - attempt.started_at).total_seconds() * 1000
        if attempt.finished_at is not None
        else None
    )
    return WorkerAttemptSummary(
        attempt_id=attempt.id,
        job_id=job.id,
        job_type_id=job.job_type_id,
        type=job.type,
        queue=job.queue,
        worker_id=attempt.worker_id,
        attempt_number=attempt.attempt_number,
        attempt_status=attempt.status,
        current_job_status=job.status,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        duration_ms=duration_ms,
        error=attempt.error,
    )
