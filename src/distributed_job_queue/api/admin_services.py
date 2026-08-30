"""Global Admin dashboard services."""

import base64
import binascii
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from distributed_job_queue.api.admin_schemas import (
    AdminOverviewResponse,
    AdminQueueListResponse,
    AdminQueueSummary,
    AdminWorkerListResponse,
    AdminWorkerSummary,
    OperationalTrendPoint,
    OperationalTrendSeries,
    OperationalTrendsResponse,
)
from distributed_job_queue.api.dashboard_services import get_dashboard_analytics
from distributed_job_queue.common.prometheus import (
    TREND_WINDOWS,
    PrometheusQueryClient,
    PrometheusQueryError,
)
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.repositories.admin_dashboard import (
    AdminDashboardRepository,
    AdminWorkerCursor,
    AdminWorkerFilters,
)
from distributed_job_queue.persistence.repositories.dashboard import DashboardJobFilters
from distributed_job_queue.queueing import RedisQueue

logger = logging.getLogger(__name__)


class InvalidAdminDashboardFilter(ValueError):
    """Raised when an Admin dashboard cursor is malformed."""


def get_admin_overview(
    session: Session,
    prometheus: PrometheusQueryClient | None,
    *,
    admin_id: str,
    window: str,
    now: datetime | None = None,
) -> AdminOverviewResponse:
    """Combine exact PostgreSQL totals with global operational trends."""

    end = now or datetime.now(timezone.utc)
    definition = TREND_WINDOWS[window]
    exact = get_dashboard_analytics(
        session,
        owner="admin",
        owner_id=admin_id,
        filters=DashboardJobFilters(),
    )
    if prometheus is None:
        operational = OperationalTrendsResponse(
            available=False,
            unavailable_reason="not_configured",
            window=window,
            start=end - definition.duration,
            end=end,
            step_seconds=definition.step_seconds,
            series=[],
        )
    else:
        try:
            result = prometheus.dashboard_trends(window, end)
            operational = OperationalTrendsResponse(
                available=True,
                unavailable_reason=None,
                window=window,
                start=result.start,
                end=result.end,
                step_seconds=result.step_seconds,
                series=[
                    OperationalTrendSeries(
                        metric=series.key,
                        unit=series.unit,
                        labels=series.labels,
                        points=[
                            OperationalTrendPoint(
                                timestamp=point.timestamp,
                                value=point.value,
                            )
                            for point in series.points
                        ],
                    )
                    for series in result.series
                ],
            )
        except (PrometheusQueryError, OSError):
            logger.exception(
                "Admin Prometheus trend query failed",
                extra={"event": "admin.operational_trends.query_failed"},
            )
            operational = OperationalTrendsResponse(
                available=False,
                unavailable_reason="temporarily_unavailable",
                window=window,
                start=end - definition.duration,
                end=end,
                step_seconds=definition.step_seconds,
                series=[],
            )
    return AdminOverviewResponse(exact=exact, operational=operational)


def list_admin_workers(
    session: Session,
    *,
    filters: AdminWorkerFilters,
    limit: int,
    cursor: str | None,
) -> AdminWorkerListResponse:
    decoded = _decode_worker_cursor(cursor) if cursor else None
    rows = AdminDashboardRepository(session).list_workers(
        filters=filters,
        limit=limit,
        cursor=decoded,
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    return AdminWorkerListResponse(
        items=[
            AdminWorkerSummary(
                worker_id=row.worker.id,
                owner_user_id=row.worker.owner_user_id,
                capabilities=row.worker.capabilities,
                status=row.worker.status,
                active_jobs=row.active_jobs,
                registered_at=row.worker.registered_at,
                last_heartbeat_at=row.worker.last_heartbeat_at,
            )
            for row in page
        ],
        next_cursor=(
            _encode_worker_cursor(page[-1].worker.registered_at, page[-1].worker.id)
            if has_more and page
            else None
        ),
    )


def get_admin_queues(
    session: Session,
    queue: RedisQueue,
) -> AdminQueueListResponse:
    grouped: dict[str, dict[str, object]] = {}
    for queue_name, status, count, oldest in AdminDashboardRepository(
        session
    ).queue_status_rows():
        item = grouped.setdefault(
            queue_name,
            {
                "counts": {job_status.value: 0 for job_status in JobStatus},
                "oldest_queued_at": None,
            },
        )
        counts = item["counts"]
        assert isinstance(counts, dict)
        counts[status] = count
        if status == JobStatus.QUEUED.value:
            item["oldest_queued_at"] = oldest

    redis_available = True
    items: list[AdminQueueSummary] = []
    for queue_name, values in grouped.items():
        counts = values["counts"]
        assert isinstance(counts, dict)
        try:
            ready = queue.queue_size(queue_name)
            inflight = queue.inflight_size(queue_name)
        except Exception:
            logger.exception(
                "Admin Redis queue-state read failed",
                extra={"event": "admin.queue_state.redis_failed", "queue": queue_name},
            )
            redis_available = False
            ready = None
            inflight = None
        items.append(
            AdminQueueSummary(
                queue=queue_name,
                durable_jobs=sum(counts.values()),
                status_counts=counts,
                oldest_queued_at=values["oldest_queued_at"],
                redis_ready_jobs=ready,
                redis_inflight_jobs=inflight,
            )
        )
    return AdminQueueListResponse(redis_available=redis_available, items=items)


def _encode_worker_cursor(registered_at: datetime, worker_id: str) -> str:
    raw = json.dumps(
        {"registered_at": registered_at.isoformat(), "worker_id": worker_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_worker_cursor(value: str) -> AdminWorkerCursor:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(value + padding))
        registered_at = datetime.fromisoformat(decoded["registered_at"])
        worker_id = decoded["worker_id"]
        if registered_at.tzinfo is None or not isinstance(worker_id, str) or not worker_id:
            raise ValueError
        return AdminWorkerCursor(registered_at=registered_at, worker_id=worker_id)
    except (ValueError, TypeError, KeyError, binascii.Error) as exc:
        raise InvalidAdminDashboardFilter("Cursor is invalid") from exc
