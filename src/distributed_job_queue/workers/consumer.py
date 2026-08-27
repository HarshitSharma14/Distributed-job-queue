"""Worker-side Redis claim and PostgreSQL handoff."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import sessionmaker

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.repositories import (
    ConcurrentJobUpdate,
    JobRepository,
)
from distributed_job_queue.queueing import JobLease, RedisQueue
from distributed_job_queue.workers.handlers import HandlerRegistry, JobHandler


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: str
    type: str
    payload: dict[str, Any]
    lease: JobLease
    handler: JobHandler


class WorkerConsumer:
    """Claims ready jobs and makes their ownership durable in PostgreSQL."""

    def __init__(
        self,
        queue: RedisQueue,
        handlers: HandlerRegistry,
        *,
        session_factory: sessionmaker = SessionFactory,
    ) -> None:
        self.queue = queue
        self.handlers = handlers
        self.session_factory = session_factory

    def claim_next(
        self,
        queue_name: str,
        *,
        worker_id: str,
        lease_seconds: int,
        wait_seconds: int,
    ) -> ClaimedJob | None:
        lease = self.queue.long_poll(
            queue_name,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            wait_seconds=wait_seconds,
        )
        if lease is None:
            return None

        try:
            with self.session_factory.begin() as session:
                repository = JobRepository(session)
                job = repository.get(lease.job_id)
                if job is None or job.status != JobStatus.QUEUED.value:
                    self._release_stale(lease)
                    return None

                handler = self.handlers.handler(job.type)
                repository.mark_running(
                    job.id,
                    worker_id=worker_id,
                    lease_token=lease.token,
                    lease_expires_at=datetime.now(timezone.utc)
                    + timedelta(seconds=lease_seconds),
                )
                return ClaimedJob(
                    id=job.id,
                    type=job.type,
                    payload=dict(job.payload),
                    lease=lease,
                    handler=handler,
                )
        except ConcurrentJobUpdate:
            self._release_stale(lease)
            return None
        except Exception:
            self.queue.abandon_claim(
                lease.job_id,
                queue=lease.queue,
                worker_id=lease.worker_id,
                token=lease.token,
            )
            raise

    def _release_stale(self, lease: JobLease) -> None:
        self.queue.release_lease(
            lease.job_id,
            queue=lease.queue,
            worker_id=lease.worker_id,
            token=lease.token,
        )
