import pytest

from distributed_job_queue.workers.handlers import (
    DuplicateJobHandler,
    HandlerRegistry,
    UnknownJobHandler,
)


def test_register_and_resolve_handler():
    registry = HandlerRegistry()

    def generate_report(payload):
        return payload["report_id"]

    registry.register("generate_report", generate_report)

    assert registry.handles("generate_report") is True
    assert registry.handler("generate_report")({"report_id": 42}) == 42


def test_duplicate_and_unknown_handlers_are_rejected():
    registry = HandlerRegistry()
    registry.register("generate_report", lambda payload: payload)

    with pytest.raises(DuplicateJobHandler, match="generate_report"):
        registry.register("generate_report", lambda payload: payload)
    with pytest.raises(UnknownJobHandler, match="send_email"):
        registry.handler("send_email")
