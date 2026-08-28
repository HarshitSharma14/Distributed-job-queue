"""Stable API error contract and FastAPI exception handlers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from distributed_job_queue.common.logging import request_id_context

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class APIError(Exception):
    status_code: int
    code: str
    message: str
    headers: dict[str, str] | None = None

    def __str__(self) -> str:
        return self.message


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def handle_api_error(_request: Request, exc: APIError) -> JSONResponse:
        _log_api_error(exc.code, exc.status_code)
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": [str(part) for part in error["loc"]],
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        _log_api_error("VALIDATION_ERROR", 422)
        return _error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=details,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        _log_api_error("HTTP_ERROR", exc.status_code)
        return _error_response(
            status_code=exc.status_code,
            code="HTTP_ERROR",
            message=str(exc.detail),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error", extra={"event": "api.unhandled_error"})
        return _error_response(
            status_code=500,
            code="INTERNAL_ERROR",
            message="An unexpected error occurred",
        )


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id_context.get(),
    }
    if details is not None:
        error["details"] = details
    return JSONResponse(
        status_code=status_code,
        content={"error": error},
        headers=headers,
    )


def _log_api_error(code: str, status_code: int) -> None:
    level = logging.WARNING if status_code < 500 else logging.ERROR
    logger.log(
        level,
        "API request rejected",
        extra={"event": "api.request_rejected", "error_code": code, "status_code": status_code},
    )
