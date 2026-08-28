"""Safe handler execution with lease renewal and fenced finalization."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.workers.consumer import ClaimedJob
from distributed_job_queue.workers.gateway_client import (
    GatewayLeaseRejected,
    WorkerGatewayClient,
    WorkerLease,
)


class LeaseLost(RuntimeError):
    """Raised when a worker can no longer prove ownership of a running job."""


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    status: JobStatus
    result: Any = None
    error: dict[str, str] | None = None


class LeaseRenewer:
    """Renews the same fenced lease through the Worker Gateway."""

    def __init__(
        self,
        gateway: WorkerGatewayClient,
        lease: WorkerLease,
        *,
        interval_seconds: float,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        self.gateway = gateway
        self.lease = lease
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._error: Exception | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"lease-renewer-{lease.job_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()

    def ensure_owned(self) -> None:
        if self._lost.is_set():
            error = LeaseLost(f"Lease lost for job {self.lease.job_id}")
            if self._error is not None:
                raise error from self._error
            raise error

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                if not self.gateway.renew(self.lease):
                    self._lost.set()
                    return
            except Exception as exc:
                self._error = exc
                self._lost.set()
                return


class WorkerExecutor:
    """Runs one handler and reports its outcome through the gateway."""

    def __init__(
        self,
        gateway: WorkerGatewayClient,
        *,
        lease_seconds: int,
        renewal_interval_seconds: float | None = None,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        self.gateway = gateway
        self.renewal_interval_seconds = renewal_interval_seconds or max(
            1.0, lease_seconds / 3
        )

    def execute(self, claimed: ClaimedJob) -> ExecutionOutcome:
        renewer = LeaseRenewer(
            self.gateway,
            claimed.lease,
            interval_seconds=self.renewal_interval_seconds,
        )
        renewer.start()
        try:
            try:
                result = claimed.handler(claimed.payload)
            except Exception as exc:
                renewer.stop()
                renewer.ensure_owned()
                error = {"type": type(exc).__name__, "message": str(exc)}
                try:
                    status = self.gateway.fail(claimed.lease, error=error)
                except GatewayLeaseRejected as gateway_error:
                    raise LeaseLost(f"Lease lost for job {claimed.id}") from gateway_error
                return ExecutionOutcome(
                    status=status,
                    error=error,
                )

            renewer.stop()
            renewer.ensure_owned()
            try:
                status = self.gateway.complete(claimed.lease)
            except GatewayLeaseRejected as gateway_error:
                raise LeaseLost(f"Lease lost for job {claimed.id}") from gateway_error
            return ExecutionOutcome(
                status=status,
                result=result,
            )
        finally:
            renewer.stop()
