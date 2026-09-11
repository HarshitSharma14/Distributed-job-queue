"""Minimal health endpoints without infrastructure or credential disclosure."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.common.config import load_settings
from distributed_job_queue.api.dependencies import (
    get_handler_storage,
    get_result_storage,
)

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live():
    return {"status": "ok"}


@router.get("/health/ready")
def ready():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM users LIMIT 1"))
        with Redis.from_url(
            load_settings().redis_url, socket_connect_timeout=2, socket_timeout=2
        ) as client:
            client.ping()
        for storage in (get_handler_storage(), get_result_storage()):
            if not storage.client.bucket_exists(storage.bucket):
                raise RuntimeError("Bucket missing")
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ready"}
