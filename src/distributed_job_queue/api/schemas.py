"""Public API request and response contracts."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.domain.worker import WorkerStatus

NAME_PATTERN = r"^[A-Za-z0-9_.-]+$"
WorkerCapability = Annotated[
    str, Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
]


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


class WorkerRegistrationRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    capabilities: list[WorkerCapability] = Field(min_length=1, max_length=100)


class WorkerRegistrationResponse(BaseModel):
    worker_id: str
    capabilities: list[str]
    status: WorkerStatus
    registered_at: datetime
    last_heartbeat_at: datetime
    heartbeat_interval_seconds: int


class WorkerHeartbeatResponse(BaseModel):
    worker_id: str
    status: WorkerStatus
    last_heartbeat_at: datetime


class WorkerClaimRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    queue: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    wait_seconds: int | None = Field(default=None, ge=0, le=30)


class WorkerClaimResponse(BaseModel):
    job_id: str
    attempt_number: int
    type: str
    queue: str
    payload: dict[str, Any]
    lease_token: str
    lease_expires_at: datetime


class WorkerLeaseRenewRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    lease_token: UUID


class WorkerLeaseRenewResponse(BaseModel):
    job_id: str
    worker_id: str
    lease_expires_at: datetime


class WorkerCompletionRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    lease_token: UUID
    result_ref: str | None = Field(default=None, min_length=1, max_length=2_048)


class WorkerFailureDetail(BaseModel):
    type: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4_000)
    details: dict[str, Any] | None = None


class WorkerFailureRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    lease_token: UUID
    error: WorkerFailureDetail


class WorkerFinalizationResponse(BaseModel):
    job_id: str
    status: JobStatus
    attempt_number: int
    result_ref: str | None
    error: dict[str, Any] | None
    replayed: bool
