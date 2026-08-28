"""Human authentication API contracts."""

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
