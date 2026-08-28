"""Structured JSON logging with request context and secret redaction."""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)
_SENSITIVE_KEY_PARTS = (
    "access_key",
    "api_key",
    "authorization",
    "credential",
    "lease_token",
    "password",
    "secret",
    "signed_url",
    "token",
    "upload_url",
)
_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+")
_SIGNED_QUERY_PATTERN = re.compile(r"(https?://[^\s?]+)\?[^\s]+")


def bind_request_id(request_id: str) -> Token[str | None]:
    return request_id_context.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    request_id_context.reset(token)


class JsonFormatter(logging.Formatter):
    """Render one safe, machine-readable JSON object per log record."""

    def __init__(self, *, service: str, secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.service = service
        self.secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", record.getMessage())
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "event": self._sanitize_text(str(event)),
        }
        request_id = getattr(record, "request_id", None) or request_id_context.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key in payload or key == "event":
                continue
            payload[key] = self._redact(value, key=key)
        if record.exc_info:
            payload["exception"] = self._sanitize_text(
                "".join(self.formatException(record.exc_info))
            )
        return json.dumps(payload, separators=(",", ":"), default=str)

    def _redact(self, value: Any, *, key: str = "") -> Any:
        normalized_key = key.lower()
        if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {item_key: self._redact(item, key=str(item_key)) for item_key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._redact(item) for item in value]
        if isinstance(value, str):
            return self._sanitize_text(value)
        return value

    def _sanitize_text(self, value: str) -> str:
        sanitized = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
        sanitized = _SIGNED_QUERY_PATTERN.sub(r"\1?[REDACTED]", sanitized)
        for secret in self.secrets:
            sanitized = sanitized.replace(secret, "[REDACTED]")
        return sanitized


def configure_logging(
    service: str,
    *,
    debug: bool = False,
    secrets: tuple[str, ...] = (),
) -> None:
    """Configure the root logger once for one executable process."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service=service, secrets=secrets))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
