"""Durable release of delayed retry jobs."""

from datetime import datetime

from sqlalchemy.orm import Session

from distributed_job_queue.persistence.repositories import JobRepository


def release_due_retries(
    session: Session,
    *,
    now: datetime,
    limit: int,
) -> list[str]:
    """Queue one locked batch of retries and return their job IDs."""

    jobs = JobRepository(session).release_due_retries(now=now, limit=limit)
    return [job.id for job in jobs]
