"""FastAPI dependencies shared by API routes."""

from collections.abc import Iterator
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis import Redis
from sqlalchemy.orm import Session

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.queueing import RedisQueue
from distributed_job_queue.storage import MinioResultStorage

worker_bearer = HTTPBearer(auto_error=False)
metrics_bearer = HTTPBearer(auto_error=False)


def get_session() -> Iterator[Session]:
    """Provide one transaction that commits only after the request succeeds."""

    with SessionFactory.begin() as session:
        yield session


def get_session_factory():
    """Provide a factory for operations that must not span a long poll."""

    return SessionFactory


def get_redis_queue() -> Iterator[RedisQueue]:
    """Keep Redis credentials and connections inside the gateway process."""

    client = Redis.from_url(load_settings().redis_url, decode_responses=True)
    try:
        yield RedisQueue(client)
    finally:
        client.close()


def get_result_storage() -> MinioResultStorage:
    """Keep permanent object-storage credentials inside the platform."""

    settings = load_settings()
    return MinioResultStorage(
        settings.minio_endpoint,
        settings.minio_access_key,
        settings.minio_secret_key,
        settings.minio_bucket,
    )


def require_worker_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(worker_bearer)
    ],
) -> None:
    """Protect the gateway until the complete credential model is designed."""

    expected_token = load_settings().worker_gateway_token
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not compare_digest(credentials.credentials, expected_token)
    ):
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="WORKER_UNAUTHORIZED",
            message="Invalid worker token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_metrics_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(metrics_bearer)
    ],
) -> None:
    """Protect operational metrics from public dashboard users."""

    expected_token = load_settings().metrics_token
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not compare_digest(credentials.credentials, expected_token)
    ):
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="METRICS_UNAUTHORIZED",
            message="Invalid metrics token",
            headers={"WWW-Authenticate": "Bearer"},
        )
