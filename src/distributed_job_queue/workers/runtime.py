"""Worker registration and heartbeat runtime."""

from __future__ import annotations

import os
import socket
import uuid
from datetime import datetime, timezone

from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.repositories import WorkerRepository


def create_worker_id(name: str | None = None) -> str:
    """Return one stable ID for the lifetime of this process instance."""

    if name:
        return name
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4()}"


def register_worker(worker_id: str, capabilities: list[str]) -> None:
    with SessionFactory.begin() as session:
        WorkerRepository(session).register(
            worker_id,
            capabilities=capabilities,
            now=datetime.now(timezone.utc),
        )


def heartbeat_worker(worker_id: str) -> bool:
    with SessionFactory.begin() as session:
        return WorkerRepository(session).heartbeat(
            worker_id, now=datetime.now(timezone.utc)
        )


def mark_worker_offline(worker_id: str) -> bool:
    with SessionFactory.begin() as session:
        return WorkerRepository(session).mark_offline(worker_id)
