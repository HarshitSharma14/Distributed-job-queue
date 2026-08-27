"""Public API request and response contracts."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from distributed_job_queue.domain.job import JobStatus

NAME_PATTERN = r"^[A-Za-z0-9_.-]+$"


class JobCreateRequest(BaseModel):
    type: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    queue: str = Field(
        default="default", min_length=1, max_length=100, pattern=NAME_PATTERN
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=0, le=1_000_000)
    max_attempts: int | None = Field(default=None, ge=1, le=100)


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus
    type: str
    queue: str
    priority: int
    created_at: datetime


class JobAttemptResponse(BaseModel):
    attempt_number: int
    worker_id: str
    status: JobStatus
    started_at: datetime
    finished_at: datetime | None
    error: dict[str, Any] | None


class JobDetailResponse(BaseModel):
    job_id: str
    type: str
    queue: str
    payload: dict[str, Any]
    priority: int
    status: JobStatus
    attempt_count: int
    max_attempts: int
    available_at: datetime
    worker_id: str | None
    lease_expires_at: datetime | None
    result_ref: str | None
    error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    attempt_history: list[JobAttemptResponse]
