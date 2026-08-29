from pathlib import Path

import pytest

from distributed_job_queue.workers.sandbox import (
    DockerHandlerSandbox,
    SandboxExecutionError,
)


def test_downloaded_handler_runs_without_host_secrets_network_or_write_access(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DJQ_HOST_SECRET", "must-not-enter-container")
    handler = Path(tmp_path) / "handler.py"
    handler.write_text(
        """
import os
import socket

def handle(payload):
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=0.25)
        network_blocked = False
    except OSError:
        network_blocked = True
    try:
        open("/opt/handler/escaped.txt", "w").write("unsafe")
        read_only = False
    except OSError:
        read_only = True
    return {
        "value": payload["value"],
        "host_secret": os.getenv("DJQ_HOST_SECRET"),
        "network_blocked": network_blocked,
        "read_only": read_only,
        "uid": os.getuid(),
    }
""".strip()
    )
    handler.chmod(0o644)
    Path(tmp_path).chmod(0o755)
    sandbox = DockerHandlerSandbox(
        image=(
            "python:3.12-slim@sha256:"
            "09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217"
        ),
        memory_mb=128,
        millicpus=500,
        pids_limit=32,
        timeout_seconds=15,
        max_output_bytes=64 * 1024,
    )

    result = sandbox.execute(Path(tmp_path), "handler:handle", {"value": 42})

    assert result == {
        "value": 42,
        "host_secret": None,
        "network_blocked": True,
        "read_only": True,
        "uid": 65534,
    }
    assert not (Path(tmp_path) / "escaped.txt").exists()


def test_sandbox_terminates_handler_after_execution_deadline(tmp_path):
    handler = Path(tmp_path) / "handler.py"
    handler.write_text(
        "import time\n\ndef handle(payload):\n    time.sleep(10)\n"
    )
    handler.chmod(0o644)
    Path(tmp_path).chmod(0o755)
    sandbox = DockerHandlerSandbox(
        image=(
            "python:3.12-slim@sha256:"
            "09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217"
        ),
        memory_mb=128,
        millicpus=500,
        pids_limit=32,
        timeout_seconds=1,
        max_output_bytes=64 * 1024,
    )

    with pytest.raises(SandboxExecutionError, match="timed out"):
        sandbox.execute(Path(tmp_path), "handler:handle", {})
