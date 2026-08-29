"""Ephemeral Docker isolation for Publisher-provided Python handlers."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4


class SandboxExecutionError(RuntimeError):
    """Raised when isolated handler execution cannot safely complete."""


class DockerHandlerSandbox:
    def __init__(
        self,
        *,
        image: str,
        memory_mb: int,
        millicpus: int,
        pids_limit: int,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> None:
        if not image:
            raise ValueError("sandbox image must not be empty")
        self.image = image
        self.memory_mb = memory_mb
        self.millicpus = millicpus
        self.pids_limit = pids_limit
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def execute(
        self,
        bundle_root: Path,
        entrypoint: str,
        payload: dict[str, Any],
    ) -> Any:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(encoded) > self.max_output_bytes:
            raise SandboxExecutionError("Sandbox input exceeds the size limit")

        container_name = f"djq-handler-{uuid4().hex}"
        command = self.command(bundle_root, entrypoint, container_name=container_name)
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise SandboxExecutionError(
                "Docker is required for downloaded handler execution"
            ) from exc

        stdout = bytearray()
        stderr = bytearray()
        overflow = threading.Event()
        readers = [
            threading.Thread(
                target=_bounded_read,
                args=(process.stdout, stdout, self.max_output_bytes, overflow),
                daemon=True,
            ),
            threading.Thread(
                target=_bounded_read,
                args=(process.stderr, stderr, self.max_output_bytes, overflow),
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()
        try:
            assert process.stdin is not None
            try:
                process.stdin.write(encoded)
                process.stdin.close()
            except OSError as exc:
                process.kill()
                _remove_container(container_name)
                raise SandboxExecutionError(
                    "Handler sandbox stopped before receiving its payload"
                ) from exc
            try:
                process.wait(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                _remove_container(container_name)
                process.wait()
                raise SandboxExecutionError("Handler execution timed out") from exc
            if overflow.is_set():
                process.kill()
                _remove_container(container_name)
                process.wait()
                raise SandboxExecutionError("Sandbox output exceeds the size limit")
        finally:
            for reader in readers:
                reader.join(timeout=2)

        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[-2_000:].strip()
            raise SandboxExecutionError(
                f"Handler sandbox failed: {detail or 'container exited unsuccessfully'}"
            )
        try:
            response = json.loads(stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SandboxExecutionError("Handler sandbox returned invalid output") from exc
        if not isinstance(response, dict) or response.get("ok") is not True:
            error = response.get("error") if isinstance(response, dict) else None
            raise SandboxExecutionError(str(error or "Handler execution failed"))
        return response.get("result")

    def command(
        self, bundle_root: Path, entrypoint: str, *, container_name: str
    ) -> list[str]:
        runner = Path(__file__).with_name("sandbox_entrypoint.py").resolve()
        return [
            "docker",
            "run",
            "--rm",
            "--interactive",
            "--name",
            container_name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "--pids-limit",
            str(self.pids_limit),
            "--memory",
            f"{self.memory_mb}m",
            "--memory-swap",
            f"{self.memory_mb}m",
            "--cpus",
            str(self.millicpus / 1000),
            "--ulimit",
            "nofile=64:64",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=16m",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--volume",
            f"{bundle_root.resolve()}:/opt/handler:ro",
            "--volume",
            f"{runner}:/opt/djq/sandbox_entrypoint.py:ro",
            self.image,
            "python",
            "-I",
            "/opt/djq/sandbox_entrypoint.py",
            entrypoint,
        ]


def _bounded_read(
    stream: BinaryIO | None,
    target: bytearray,
    limit: int,
    overflow: threading.Event,
) -> None:
    if stream is None:
        return
    while chunk := stream.read(8_192):
        remaining = limit - len(target)
        if remaining > 0:
            target.extend(chunk[:remaining])
        if len(chunk) > remaining:
            overflow.set()


def _remove_container(container_name: str) -> None:
    subprocess.run(
        ["docker", "rm", "--force", container_name],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
