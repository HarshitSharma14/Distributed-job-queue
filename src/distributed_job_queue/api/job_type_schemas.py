"""Publisher Job Type API contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from distributed_job_queue.api.schemas import NAME_PATTERN
from distributed_job_queue.domain.identity import HandlerArtifactStatus, JobTypeStatus


class JobTypeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    queue: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)


class JobTypeResponse(BaseModel):
    job_type_id: str
    publisher_id: str
    name: str
    version: int
    queue: str
    status: JobTypeStatus
    handler_ref: str | None
    handler_digest: str | None
    created_at: datetime
    updated_at: datetime


class HandlerUploadRequest(BaseModel):
    expected_sha256: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    size_bytes: int = Field(ge=1)


class HandlerUploadResponse(BaseModel):
    artifact_id: str
    job_type_id: str
    object_ref: str
    upload_url: str
    expires_at: datetime


class HandlerVerificationResponse(BaseModel):
    artifact_id: str
    artifact_status: HandlerArtifactStatus
    job_type_status: JobTypeStatus
    expected_sha256: str
    actual_sha256: str | None
    expected_size_bytes: int
    actual_size_bytes: int | None
    rejection_reason: str | None
