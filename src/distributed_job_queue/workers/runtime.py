"""Infrastructure-independent worker process identity."""

from __future__ import annotations

import os
import socket
import uuid


def create_worker_id(name: str | None = None) -> str:
    """Return one stable ID for the lifetime of this process instance."""

    if name:
        return name
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4()}"
