"""Worker-side job claiming through the Worker Gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from distributed_job_queue.workers.gateway_client import (
    WorkerGatewayClient,
    WorkerLease,
)
from distributed_job_queue.workers.handlers import HandlerRegistry, JobHandler


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: str
    type: str
    payload: dict[str, Any]
    lease: WorkerLease
    handler: JobHandler


class WorkerConsumer:
    """Claims jobs through the gateway and attaches a local handler."""

    def __init__(
        self,
        gateway: WorkerGatewayClient,
        handlers: HandlerRegistry,
    ) -> None:
        self.gateway = gateway
        self.handlers = handlers

    def claim_next(
        self,
        queue_name: str,
        *,
        worker_id: str,
        wait_seconds: int,
    ) -> ClaimedJob | None:
        claim = self.gateway.claim(
            queue_name,
            worker_id=worker_id,
            wait_seconds=wait_seconds,
        )
        if claim is None:
            return None
        return ClaimedJob(
            id=claim.id,
            type=claim.type,
            payload=claim.payload,
            lease=claim.lease,
            handler=self.handlers.handler(claim.type),
        )
