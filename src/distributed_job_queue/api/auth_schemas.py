"""Human authentication API contracts."""

from datetime import datetime

from pydantic import BaseModel, Field

from distributed_job_queue.domain.identity import UserRole

EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=1, max_length=1_024)


class CurrentUserResponse(BaseModel):
    user_id: str
    email: str
    display_name: str
    roles: list[UserRole]


class ProducerKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int = Field(default=90, ge=1, le=365)


class ProducerKeyCreatedResponse(BaseModel):
    credential_id: str
    name: str
    key: str
    key_prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime


class ProducerKeyResponse(BaseModel):
    credential_id: str
    name: str
    key_prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
