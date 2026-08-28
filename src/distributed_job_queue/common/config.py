"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigurationError(ValueError):
    """Raised when an environment value is missing or invalid."""


def _get_int(name: str, default: int, *, minimum: int = 0) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return parsed


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration shared by API, workers, scheduler, and recovery."""

    environment: str
    debug: bool
    api_host: str
    api_port: int
    auth_session_hours: int
    auth_cookie_secure: bool
    database_url: str
    redis_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    result_upload_url_seconds: int
    metrics_token: str
    metrics_port: int
    worker_gateway_url: str
    worker_gateway_token: str
    worker_heartbeat_interval_seconds: int
    worker_offline_after_seconds: int
    worker_long_poll_seconds: int
    job_lease_seconds: int
    retry_base_delay_seconds: int
    retry_max_delay_seconds: int
    scheduler_batch_size: int
    scheduler_poll_interval_seconds: int
    recovery_batch_size: int
    recovery_poll_interval_seconds: int
    max_attempts: int
    outbox_batch_size: int
    outbox_poll_interval_seconds: int


def load_settings() -> Settings:
    """Load settings from the process environment."""

    environment = os.getenv("APP_ENV", "development")
    worker_gateway_token = os.getenv("WORKER_GATEWAY_TOKEN")
    if not worker_gateway_token:
        if environment != "development":
            raise ConfigurationError(
                "WORKER_GATEWAY_TOKEN is required outside development"
            )
        worker_gateway_token = "dev-worker-token"
    metrics_token = os.getenv("METRICS_TOKEN")
    if not metrics_token:
        if environment != "development":
            raise ConfigurationError("METRICS_TOKEN is required outside development")
        metrics_token = "dev-metrics-token"

    return Settings(
        environment=environment,
        debug=_get_bool("APP_DEBUG", False),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=_get_int("API_PORT", 8000, minimum=1),
        auth_session_hours=_get_int("AUTH_SESSION_HOURS", 12, minimum=1),
        auth_cookie_secure=_get_bool(
            "AUTH_COOKIE_SECURE", environment != "development"
        ),
        database_url=os.getenv(
            "DATABASE_URL", "postgresql+psycopg://queue:queue@localhost:5432/queue"
        ),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        minio_endpoint=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        minio_access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        minio_secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        minio_bucket=os.getenv("MINIO_BUCKET", "job-results"),
        result_upload_url_seconds=_get_int(
            "RESULT_UPLOAD_URL_SECONDS", 300, minimum=1
        ),
        metrics_token=metrics_token,
        metrics_port=_get_int("METRICS_PORT", 0, minimum=0),
        worker_gateway_url=os.getenv(
            "WORKER_GATEWAY_URL", "http://localhost:8000"
        ),
        worker_gateway_token=worker_gateway_token,
        worker_heartbeat_interval_seconds=_get_int(
            "WORKER_HEARTBEAT_INTERVAL_SECONDS", 10, minimum=1
        ),
        worker_offline_after_seconds=_get_int(
            "WORKER_OFFLINE_AFTER_SECONDS", 60, minimum=1
        ),
        worker_long_poll_seconds=_get_int(
            "WORKER_LONG_POLL_SECONDS", 20, minimum=0
        ),
        job_lease_seconds=_get_int("JOB_LEASE_SECONDS", 60, minimum=1),
        retry_base_delay_seconds=_get_int("RETRY_BASE_DELAY_SECONDS", 5, minimum=0),
        retry_max_delay_seconds=_get_int("RETRY_MAX_DELAY_SECONDS", 300, minimum=0),
        scheduler_batch_size=_get_int("SCHEDULER_BATCH_SIZE", 100, minimum=1),
        scheduler_poll_interval_seconds=_get_int(
            "SCHEDULER_POLL_INTERVAL_SECONDS", 1, minimum=1
        ),
        recovery_batch_size=_get_int("RECOVERY_BATCH_SIZE", 100, minimum=1),
        recovery_poll_interval_seconds=_get_int(
            "RECOVERY_POLL_INTERVAL_SECONDS", 1, minimum=1
        ),
        max_attempts=_get_int("MAX_ATTEMPTS", 5, minimum=1),
        outbox_batch_size=_get_int("OUTBOX_BATCH_SIZE", 100, minimum=1),
        outbox_poll_interval_seconds=_get_int(
            "OUTBOX_POLL_INTERVAL_SECONDS", 1, minimum=1
        ),
    )
