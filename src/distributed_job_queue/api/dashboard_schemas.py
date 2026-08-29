"""Shared ownership-scoped dashboard API contracts."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from distributed_job_queue.domain.job import JobStatus


class DashboardJobSummary(BaseModel):
    job_id: str
    job_type_id: str
    publisher_id: str
    producer_id: str
    type: str
    queue: str
    priority: int
    status: JobStatus
    attempt_count: int
    max_attempts: int
    worker_id: str | None
    result_ref: str | None
    error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    dead_lettered_at: datetime | None


class DashboardJobListResponse(BaseModel):
    items: list[DashboardJobSummary]
    next_cursor: str | None


class DashboardJobTypeAnalytics(BaseModel):
    job_type_id: str
    publisher_id: str
    name: str
    version: int
    total_jobs: int
    status_counts: dict[str, int]


class DashboardAnalyticsResponse(BaseModel):
    total_jobs: int
    total_attempts: int
    average_attempts: float | None
    terminal_jobs: int
    terminal_success_rate: float | None
    average_completion_latency_ms: float | None
    status_counts: dict[str, int]
    job_types: list[DashboardJobTypeAnalytics]
