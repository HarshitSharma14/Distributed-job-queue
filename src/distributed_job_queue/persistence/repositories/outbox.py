"""Transactional outbox persistence operations."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from distributed_job_queue.persistence.models import OutboxEvent


class OutboxRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def pending(self, *, limit: int = 100) -> list[OutboxEvent]:
        statement = (
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def mark_published(self, event: OutboxEvent) -> None:
        event.published_at = datetime.now(timezone.utc)
        self.session.flush()
