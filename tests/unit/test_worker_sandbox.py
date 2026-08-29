from pathlib import Path

from distributed_job_queue.workers.sandbox import DockerHandlerSandbox


def test_docker_sandbox_command_applies_security_and_resource_boundaries(tmp_path):
    sandbox = DockerHandlerSandbox(
        image="python:3.12-slim@sha256:trusted",
        memory_mb=128,
        millicpus=250,
        pids_limit=32,
        timeout_seconds=10,
        max_output_bytes=4096,
    )

    command = sandbox.command(
        Path(tmp_path), "handler:handle", container_name="djq-test"
    )

    assert command[:3] == ["docker", "run", "--rm"]
    assert _option(command, "--network") == "none"
    assert "--read-only" in command
    assert _option(command, "--cap-drop") == "ALL"
    assert _option(command, "--security-opt") == "no-new-privileges"
    assert _option(command, "--user") == "65534:65534"
    assert _option(command, "--pids-limit") == "32"
    assert _option(command, "--memory") == "128m"
    assert _option(command, "--memory-swap") == "128m"
    assert _option(command, "--cpus") == "0.25"
    assert _option(command, "--ulimit") == "nofile=64:64"
    assert command[-5:] == [
        "python:3.12-slim@sha256:trusted",
        "python",
        "-I",
        "/opt/djq/sandbox_entrypoint.py",
        "handler:handle",
    ]


def _option(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]
