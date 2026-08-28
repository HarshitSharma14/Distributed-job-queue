"""Durable release of delayed retry jobs."""

from datetime import datetime

from sqlalchemy.orm import Session

from distributed_job_queue.persistence.repositories import JobRepository
from distributed_job_queue.common.metrics import SCHEDULER_RELEASED


def release_due_retries(
    session: Session,
    *,
    now: datetime,
    limit: int,
) -> list[str]:
    """Queue one locked batch of retries and return their job IDs."""

    jobs = JobRepository(session).release_due_retries(now=now, limit=limit)
    if jobs:
        SCHEDULER_RELEASED.inc(len(jobs))
    return [job.id for job in jobs]
