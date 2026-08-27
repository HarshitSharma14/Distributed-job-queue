from types import SimpleNamespace

import pytest

from distributed_job_queue.workers.handlers import (
    DuplicateJobHandler,
    HandlerRegistry,
    InvalidHandlerModule,
    UnknownJobHandler,
    load_handler_modules,
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


def test_load_handler_module_uses_explicit_registration_contract(monkeypatch):
    registry = HandlerRegistry()

    def register_handlers(target):
        target.register("send_email", lambda payload: payload)

    monkeypatch.setattr(
        "distributed_job_queue.workers.handlers.importlib.import_module",
        lambda name: SimpleNamespace(register_handlers=register_handlers),
    )

    load_handler_modules(registry, ["project.handlers"])

    assert registry.job_types() == ("send_email",)


def test_handler_module_without_registrar_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "distributed_job_queue.workers.handlers.importlib.import_module",
        lambda name: SimpleNamespace(),
    )

    with pytest.raises(InvalidHandlerModule, match="register_handlers"):
        load_handler_modules(HandlerRegistry(), ["broken.handlers"])
