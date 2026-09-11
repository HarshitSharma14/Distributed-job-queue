"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
import json
from pathlib import Path
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
    frontend_dist_dir: str
    auth_session_hours: int
    auth_cookie_secure: bool
    database_url: str
    redis_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    result_upload_url_seconds: int
    minio_handler_bucket: str
    handler_upload_url_seconds: int
    handler_download_url_seconds: int
    handler_max_bytes: int
    handler_max_uncompressed_bytes: int
    handler_sandbox_image: str
    handler_sandbox_memory_mb: int
    handler_sandbox_millicpus: int
    handler_sandbox_pids: int
    handler_sandbox_timeout_seconds: int
    handler_sandbox_max_output_bytes: int
    handler_signing_key_id: str
    handler_signing_private_key: str | None
    handler_trusted_public_keys: str
    metrics_token: str
    metrics_port: int
    prometheus_url: str | None
    prometheus_username: str | None
    prometheus_password: str | None
    prometheus_timeout_seconds: int
    worker_gateway_url: str
    worker_enrollment_token: str | None
    worker_credential_hours: int
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
    worker_enrollment_token = os.getenv("WORKER_ENROLLMENT_TOKEN")
    metrics_token = os.getenv("METRICS_TOKEN")
    if not metrics_token:
        if environment != "development":
            raise ConfigurationError("METRICS_TOKEN is required outside development")
        metrics_token = "dev-metrics-token"
    prometheus_url = os.getenv("PROMETHEUS_URL") or None
    prometheus_username = os.getenv("PROMETHEUS_USERNAME") or None
    prometheus_password = os.getenv("PROMETHEUS_PASSWORD") or None
    if bool(prometheus_username) != bool(prometheus_password):
        raise ConfigurationError(
            "PROMETHEUS_USERNAME and PROMETHEUS_PASSWORD must be set together"
        )
    if (prometheus_username or prometheus_password) and prometheus_url is None:
        raise ConfigurationError(
            "PROMETHEUS_URL is required when Prometheus credentials are configured"
        )

    signing = {}
    if os.getenv("HANDLER_SIGNING_FILE"):
        signing = json.loads(Path(os.environ["HANDLER_SIGNING_FILE"]).read_text())

    return Settings(
        environment=environment,
        debug=_get_bool("APP_DEBUG", False),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=_get_int("API_PORT", 8000, minimum=1),
        frontend_dist_dir=os.getenv("FRONTEND_DIST_DIR", "frontend/dist"),
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
        minio_handler_bucket=os.getenv(
            "MINIO_HANDLER_BUCKET", "handler-artifacts"
        ),
        handler_upload_url_seconds=_get_int(
            "HANDLER_UPLOAD_URL_SECONDS", 300, minimum=1
        ),
        handler_download_url_seconds=_get_int(
            "HANDLER_DOWNLOAD_URL_SECONDS", 300, minimum=1
        ),
        handler_max_bytes=_get_int(
            "HANDLER_MAX_BYTES", 10 * 1024 * 1024, minimum=1
        ),
        handler_max_uncompressed_bytes=_get_int(
            "HANDLER_MAX_UNCOMPRESSED_BYTES", 50 * 1024 * 1024, minimum=1
        ),
        handler_sandbox_image=os.getenv(
            "HANDLER_SANDBOX_IMAGE",
            "python:3.12-slim@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217",
        ),
        handler_sandbox_memory_mb=_get_int(
            "HANDLER_SANDBOX_MEMORY_MB", 256, minimum=32
        ),
        handler_sandbox_millicpus=_get_int(
            "HANDLER_SANDBOX_MILLICPUS", 500, minimum=10
        ),
        handler_sandbox_pids=_get_int("HANDLER_SANDBOX_PIDS", 64, minimum=1),
        handler_sandbox_timeout_seconds=_get_int(
            "HANDLER_SANDBOX_TIMEOUT_SECONDS", 300, minimum=1
        ),
        handler_sandbox_max_output_bytes=_get_int(
            "HANDLER_SANDBOX_MAX_OUTPUT_BYTES", 1024 * 1024, minimum=1024
        ),
        handler_signing_key_id=os.getenv("HANDLER_SIGNING_KEY_ID", signing.get("key_id", "local-dev")),
        handler_signing_private_key=os.getenv("HANDLER_SIGNING_PRIVATE_KEY") or signing.get("private_key"),
        handler_trusted_public_keys=os.getenv(
            "HANDLER_TRUSTED_PUBLIC_KEYS", json.dumps({signing["key_id"]: signing["public_key"]}) if signing else "{}"
        ),
        metrics_token=metrics_token,
        metrics_port=_get_int("METRICS_PORT", 0, minimum=0),
        prometheus_url=prometheus_url,
        prometheus_username=prometheus_username,
        prometheus_password=prometheus_password,
        prometheus_timeout_seconds=_get_int(
            "PROMETHEUS_TIMEOUT_SECONDS", 5, minimum=1
        ),
        worker_gateway_url=os.getenv(
            "WORKER_GATEWAY_URL", "http://localhost:8000"
        ),
        worker_enrollment_token=worker_enrollment_token,
        worker_credential_hours=_get_int(
            "WORKER_CREDENTIAL_HOURS", 24, minimum=1
        ),
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
