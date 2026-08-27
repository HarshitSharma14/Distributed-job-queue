"""Safe handler execution with lease renewal and fenced finalization."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import sessionmaker

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.repositories import JobRepository
from distributed_job_queue.queueing import JobLease, RedisQueue
from distributed_job_queue.workers.consumer import ClaimedJob


class LeaseLost(RuntimeError):
    """Raised when a worker can no longer prove ownership of a running job."""


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    status: JobStatus
    result: Any = None
    error: dict[str, str] | None = None
    lease_released: bool = False


class LeaseRenewer:
    """Renews the same fenced lease in PostgreSQL and Redis."""

    def __init__(
        self,
        queue: RedisQueue,
        lease: JobLease,
        *,
        lease_seconds: int,
        interval_seconds: float | None = None,
        session_factory: sessionmaker = SessionFactory,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        if interval_seconds is not None and interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        self.queue = queue
        self.lease = lease
        self.lease_seconds = lease_seconds
        self.interval_seconds = interval_seconds or max(1.0, lease_seconds / 3)
        self.session_factory = session_factory
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
                now = datetime.now(timezone.utc)
                expires_at = now + timedelta(seconds=self.lease_seconds)
                with self.session_factory.begin() as session:
                    renewed_in_postgres = JobRepository(session).renew_lease(
                        self.lease.job_id,
                        worker_id=self.lease.worker_id,
                        lease_token=self.lease.token,
                        now=now,
                        lease_expires_at=expires_at,
                    )
                if not renewed_in_postgres:
                    self._lost.set()
                    return
                renewed_in_redis = self.queue.renew_lease(
                    self.lease.job_id,
                    queue=self.lease.queue,
                    worker_id=self.lease.worker_id,
                    token=self.lease.token,
                    lease_seconds=self.lease_seconds,
                )
                if not renewed_in_redis:
                    self._lost.set()
                    return
            except Exception as exc:
                self._error = exc
                self._lost.set()
                return


class WorkerExecutor:
    """Runs one claimed handler and durably records its outcome."""

    def __init__(
        self,
        queue: RedisQueue,
        *,
        lease_seconds: int,
        renewal_interval_seconds: float | None = None,
        session_factory: sessionmaker = SessionFactory,
    ) -> None:
        self.queue = queue
        self.lease_seconds = lease_seconds
        self.renewal_interval_seconds = renewal_interval_seconds
        self.session_factory = session_factory

    def execute(self, claimed: ClaimedJob) -> ExecutionOutcome:
        renewer = LeaseRenewer(
            self.queue,
            claimed.lease,
            lease_seconds=self.lease_seconds,
            interval_seconds=self.renewal_interval_seconds,
            session_factory=self.session_factory,
        )
        renewer.start()
        try:
            try:
                result = claimed.handler(claimed.payload)
            except Exception as exc:
                renewer.stop()
                renewer.ensure_owned()
                error = {"type": type(exc).__name__, "message": str(exc)}
                with self.session_factory.begin() as session:
                    job = JobRepository(session).fail_execution(
                        claimed.id,
                        worker_id=claimed.lease.worker_id,
                        lease_token=claimed.lease.token,
                        error=error,
                        now=datetime.now(timezone.utc),
                    )
                    status = JobStatus(job.status)
                return ExecutionOutcome(
                    status=status,
                    error=error,
                    lease_released=self._release(claimed.lease),
                )

            renewer.stop()
            renewer.ensure_owned()
            with self.session_factory.begin() as session:
                JobRepository(session).complete_execution(
                    claimed.id,
                    worker_id=claimed.lease.worker_id,
                    lease_token=claimed.lease.token,
                    now=datetime.now(timezone.utc),
                )
            return ExecutionOutcome(
                status=JobStatus.COMPLETED,
                result=result,
                lease_released=self._release(claimed.lease),
            )
        finally:
            renewer.stop()

    def _release(self, lease: JobLease) -> bool:
        try:
            return self.queue.release_lease(
                lease.job_id,
                queue=lease.queue,
                worker_id=lease.worker_id,
                token=lease.token,
            )
        except Exception:
            return False
