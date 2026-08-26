"""Publish durable PostgreSQL outbox events to Redis."""

from sqlalchemy.orm import Session

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.models import Job, OutboxEvent
from distributed_job_queue.persistence.repositories import OutboxRepository
from distributed_job_queue.queueing import RedisQueue


class OutboxPublishError(RuntimeError):
    """Raised when a pending outbox event cannot be safely published."""


class OutboxPublisher:
    """Transfers pending JOB_READY events from PostgreSQL to Redis."""

    def __init__(self, queue: RedisQueue) -> None:
        self.queue = queue

    def publish_batch(self, session: Session, *, limit: int = 100) -> int:
        """Publish one locked batch inside the caller's database transaction."""

        if limit < 1:
            raise ValueError("limit must be at least 1")

        repository = OutboxRepository(session)
        events = repository.pending(limit=limit)
        for event in events:
            self._publish_event(session, repository, event)
        return len(events)

    def _publish_event(
        self,
        session: Session,
        repository: OutboxRepository,
        event: OutboxEvent,
    ) -> None:
        if event.event_type != "JOB_READY":
            raise OutboxPublishError(f"Unsupported outbox event: {event.event_type}")

        job = session.get(Job, event.job_id, with_for_update=True)
        if job is None:
            raise OutboxPublishError(f"Outbox job does not exist: {event.job_id}")
        if job.status not in {JobStatus.CREATED.value, JobStatus.QUEUED.value}:
            raise OutboxPublishError(
                f"Job {job.id} cannot be queued from status {job.status}"
            )

        payload = event.payload
        try:
            job_id = str(payload["job_id"])
            queue_name = str(payload["queue"])
            priority = int(payload["priority"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OutboxPublishError(f"Invalid JOB_READY payload: {event.id}") from exc

        if (
            job_id != job.id
            or queue_name != job.queue
            or priority != job.priority
            or not queue_name
            or priority < 0
        ):
            raise OutboxPublishError(f"Invalid JOB_READY payload: {event.id}")

        self.queue.enqueue(job_id, queue=queue_name, priority=priority)
        if job.status == JobStatus.CREATED.value:
            job.status = JobStatus.QUEUED.value
        repository.mark_published(event)
        session.flush()
