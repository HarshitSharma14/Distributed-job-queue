"""Dashboard contracts for Worker Agent enrollment and revocation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkerEnrollmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type_id: UUID
    expires_in_minutes: int = Field(default=15, ge=1, le=60)


class WorkerEnrollmentCreatedResponse(BaseModel):
    enrollment_id: str
    job_type_id: str
    token: str
    token_prefix: str
    created_at: datetime
    expires_at: datetime


class WorkerAgentResponse(BaseModel):
    worker_id: str
    capabilities: list[str]
    status: str
    registered_at: datetime
    last_heartbeat_at: datetime
    credential_id: str | None
    credential_prefix: str | None
    credential_expires_at: datetime | None
    credential_revoked_at: datetime | None
