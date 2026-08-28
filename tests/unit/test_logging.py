import json
import logging

from distributed_job_queue.common.logging import (
    JsonFormatter,
    bind_request_id,
    reset_request_id,
)


def format_record(message: str, **extra):
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(
        JsonFormatter(service="test", secrets=("platform-secret",)).format(record)
    )


def test_json_formatter_emits_context_and_structured_fields():
    token = bind_request_id("request-123")
    try:
        payload = format_record(
            "Job completed",
            event="job.completed",
            job_id="job-1",
            attempt_number=2,
        )
    finally:
        reset_request_id(token)

    assert payload["service"] == "test"
    assert payload["level"] == "INFO"
    assert payload["event"] == "job.completed"
    assert payload["request_id"] == "request-123"
    assert payload["job_id"] == "job-1"
    assert payload["attempt_number"] == 2
    assert payload["timestamp"].endswith("+00:00")


def test_json_formatter_redacts_sensitive_fields_and_text():
    payload = format_record(
        "Authorization: Bearer worker-token platform-secret "
        "https://storage.example.com/result?X-Amz-Signature=secret",
        worker_token="worker-token",
        lease_token="lease-token",
        upload_url="https://storage.example.com/signed",
        nested={"password": "password", "safe": "visible"},
    )
    encoded = json.dumps(payload)

    assert "worker-token" not in encoded
    assert "lease-token" not in encoded
    assert "platform-secret" not in encoded
    assert "X-Amz-Signature" not in encoded
    assert payload["worker_token"] == "[REDACTED]"
    assert payload["nested"] == {"password": "[REDACTED]", "safe": "visible"}
