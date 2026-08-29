import hashlib
import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from distributed_job_queue.workers.bundles import (
    InvalidDownloadedHandler,
    install_downloaded_handler,
)
from distributed_job_queue.workers.gateway_client import DownloadedHandlerBundle
from distributed_job_queue.workers.handlers import HandlerRegistry


def make_bundle(files: dict[str, str]) -> DownloadedHandlerBundle:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    encoded = output.getvalue()
    return DownloadedHandlerBundle(
        job_type_id="job-type-1",
        job_type="generate_report",
        digest=hashlib.sha256(encoded).hexdigest(),
        content=encoded,
    )


def valid_files() -> dict[str, str]:
    return {
        "manifest.json": json.dumps(
            {"job_type": "generate_report", "entrypoint": "handler:handle"}
        ),
        "handler.py": "def handle(payload):\n    return payload['report_id']\n",
    }


def test_downloaded_handler_is_loaded_only_into_assigned_registry():
    registry = HandlerRegistry()
    installed = install_downloaded_handler(
        registry,
        make_bundle(valid_files()),
        max_uncompressed_bytes=10_000,
    )
    try:
        assert registry.handler("generate_report")({"report_id": 42}) == 42
    finally:
        installed.close()


def test_downloaded_handler_rejects_unsafe_archive_paths():
    files = valid_files()
    files["../escape.py"] = "unsafe"

    with pytest.raises(InvalidDownloadedHandler, match="unsafe path"):
        install_downloaded_handler(
            HandlerRegistry(),
            make_bundle(files),
            max_uncompressed_bytes=10_000,
        )
