"""HTTP request correlation and access logging."""

import logging
import re
import time
from uuid import uuid4

from fastapi import FastAPI, Request

from distributed_job_queue.common.logging import bind_request_id, reset_request_id
from distributed_job_queue.common.metrics import HTTP_DURATION, HTTP_REQUESTS

logger = logging.getLogger(__name__)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def install_request_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlate_request(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if _REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid4())
        token = bind_request_id(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            elapsed_seconds = time.perf_counter() - started
            route = request.scope.get("route")
            route_template = getattr(route, "path", "unmatched")
            if route_template != "/metrics":
                HTTP_REQUESTS.labels(
                    method=request.method,
                    route=route_template,
                    status_code=str(response.status_code),
                ).inc()
                HTTP_DURATION.labels(
                    method=request.method,
                    route=route_template,
                ).observe(elapsed_seconds)
            logger.info(
                "HTTP request completed",
                extra={
                    "event": "http.request_completed",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(elapsed_seconds * 1000, 2),
                },
            )
            return response
        finally:
            reset_request_id(token)
