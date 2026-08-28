"""Authoritative worker-health and expired-lease recovery operations."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from distributed_job_queue.domain.retry import retry_available_at
from distributed_job_queue.persistence.repositories import (
    JobRepository,
    WorkerRepository,
)


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    offline_worker_ids: list[str]
    recovered_job_ids: list[str]


def recover_stale_work(
    session: Session,
    *,
    now: datetime,
    worker_offline_after_seconds: int,
    retry_base_delay_seconds: int,
    retry_max_delay_seconds: int,
    limit: int,
) -> RecoveryResult:
    """Mark stale workers offline and fence one batch of expired jobs."""

    cutoff = now - timedelta(seconds=worker_offline_after_seconds)
    offline_worker_ids = WorkerRepository(session).mark_stale_offline(cutoff=cutoff)
    jobs = JobRepository(session).recover_expired(
        now=now,
        limit=limit,
        retry_at_for_attempt=lambda attempt: retry_available_at(
            now,
            attempt,
            base_delay_seconds=retry_base_delay_seconds,
            max_delay_seconds=retry_max_delay_seconds,
        ),
    )
    return RecoveryResult(
        offline_worker_ids=offline_worker_ids,
        recovered_job_ids=[job.id for job in jobs],
    )
