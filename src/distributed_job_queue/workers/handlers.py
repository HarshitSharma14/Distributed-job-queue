"""Registration and lookup of executable job handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

JobHandler = Callable[[dict[str, Any]], Any]


class DuplicateJobHandler(ValueError):
    """Raised when a job type is registered more than once."""


class UnknownJobHandler(LookupError):
    """Raised when no code is registered for a claimed job type."""


class HandlerRegistry:
    """Maps durable job-type names to local executable functions."""

    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        if not job_type:
            raise ValueError("job_type must not be empty")
        if job_type in self._handlers:
            raise DuplicateJobHandler(f"Handler already registered for {job_type}")
        self._handlers[job_type] = handler

    def handler(self, job_type: str) -> JobHandler:
        try:
            return self._handlers[job_type]
        except KeyError as exc:
            raise UnknownJobHandler(f"No handler registered for {job_type}") from exc

    def handles(self, job_type: str) -> bool:
        return job_type in self._handlers
