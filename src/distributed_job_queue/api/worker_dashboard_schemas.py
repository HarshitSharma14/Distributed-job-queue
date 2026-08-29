"""Worker dashboard response contracts."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from distributed_job_queue.domain.job import JobStatus


class WorkerAssignmentSummary(BaseModel):
    job_id: str
    job_type_id: str
    type: str
    queue: str
    priority: int
    status: JobStatus
    attempt_number: int
    max_attempts: int
    worker_id: str
    lease_expires_at: datetime | None
    assigned_at: datetime


class WorkerAssignmentListResponse(BaseModel):
    items: list[WorkerAssignmentSummary]
    next_cursor: str | None


class WorkerAttemptSummary(BaseModel):
    attempt_id: str
    job_id: str
    job_type_id: str
    type: str
    queue: str
    worker_id: str
    attempt_number: int
    attempt_status: JobStatus
    current_job_status: JobStatus
    started_at: datetime
    finished_at: datetime | None
    duration_ms: float | None
    error: dict[str, Any] | None


class WorkerAttemptListResponse(BaseModel):
    items: list[WorkerAttemptSummary]
    next_cursor: str | None
