"""Global Admin dashboard response contracts."""

from datetime import datetime

from pydantic import BaseModel

from distributed_job_queue.api.dashboard_schemas import DashboardJobSummary
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
