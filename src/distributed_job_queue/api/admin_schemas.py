"""Global Admin dashboard response contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from distributed_job_queue.api.dashboard_schemas import (
    DashboardAnalyticsResponse,
    DashboardJobSummary,
)
from distributed_job_queue.domain.worker import WorkerStatus


class AdminDeadLetterListResponse(BaseModel):
    items: list[DashboardJobSummary]
    next_cursor: str | None


class AdminWorkerSummary(BaseModel):
    worker_id: str
    owner_user_id: str
    capabilities: list[str]
    status: WorkerStatus
    active_jobs: int
    registered_at: datetime
    last_heartbeat_at: datetime


class AdminWorkerListResponse(BaseModel):
    items: list[AdminWorkerSummary]
    next_cursor: str | None


class AdminQueueSummary(BaseModel):
    queue: str
    durable_jobs: int
    status_counts: dict[str, int]
    oldest_queued_at: datetime | None
    redis_ready_jobs: int | None
    redis_inflight_jobs: int | None


class AdminQueueListResponse(BaseModel):
    redis_available: bool
    items: list[AdminQueueSummary]


class OperationalTrendPoint(BaseModel):
    timestamp: datetime
    value: float | None


class OperationalTrendSeries(BaseModel):
    metric: str
    unit: str
    labels: dict[str, str]
    points: list[OperationalTrendPoint]


class OperationalTrendsResponse(BaseModel):
    available: bool
    unavailable_reason: Literal["not_configured", "temporarily_unavailable"] | None
    source: Literal["prometheus"] = "prometheus"
    window: Literal["1h", "6h", "24h", "7d"]
    start: datetime
    end: datetime
    step_seconds: int
    series: list[OperationalTrendSeries]


class AdminOverviewResponse(BaseModel):
    exact: DashboardAnalyticsResponse
    operational: OperationalTrendsResponse
