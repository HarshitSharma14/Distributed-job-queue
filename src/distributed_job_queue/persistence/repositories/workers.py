"""Persistence operations for worker registration and health."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from distributed_job_queue.domain.worker import WorkerStatus
from distributed_job_queue.persistence.models import Worker


class WorkerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def register(
        self, worker_id: str, *, capabilities: list[str], now: datetime
    ) -> Worker:
        if not worker_id:
            raise ValueError("worker_id must not be empty")
        normalized_capabilities = sorted(set(capabilities))
        statement = (
            insert(Worker)
            .values(
                id=worker_id,
                capabilities=normalized_capabilities,
                status=WorkerStatus.ONLINE.value,
                last_heartbeat_at=now,
                registered_at=now,
            )
            .on_conflict_do_update(
                index_elements=[Worker.id],
                set_={
                    "capabilities": normalized_capabilities,
                    "status": WorkerStatus.ONLINE.value,
                    "last_heartbeat_at": now,
                },
            )
            .returning(Worker)
        )
        return self.session.scalars(
            statement.execution_options(populate_existing=True)
        ).one()

    def get(self, worker_id: str) -> Worker | None:
        return self.session.get(Worker, worker_id)

    def heartbeat(self, worker_id: str, *, now: datetime) -> bool:
        statement = (
            update(Worker)
            .where(Worker.id == worker_id)
            .values(status=WorkerStatus.ONLINE.value, last_heartbeat_at=now)
        )
        return self.session.execute(statement).rowcount == 1

    def mark_offline(self, worker_id: str) -> bool:
        statement = (
            update(Worker)
            .where(Worker.id == worker_id)
            .values(status=WorkerStatus.OFFLINE.value)
        )
        return self.session.execute(statement).rowcount == 1

    def mark_stale_offline(self, *, cutoff: datetime) -> list[str]:
        statement = (
            update(Worker)
            .where(
                Worker.status == WorkerStatus.ONLINE.value,
                Worker.last_heartbeat_at < cutoff,
            )
            .values(status=WorkerStatus.OFFLINE.value)
            .returning(Worker.id)
        )
        return list(self.session.scalars(statement))

    def list_by_status(self, status: WorkerStatus) -> list[Worker]:
        statement = select(Worker).where(Worker.status == status.value).order_by(Worker.id)
        return list(self.session.scalars(statement))

    def list_by_capability(
        self, capability: str, *, status: WorkerStatus = WorkerStatus.ONLINE
    ) -> list[Worker]:
        statement = (
            select(Worker)
            .where(
                Worker.status == status.value,
                Worker.capabilities.contains([capability]),
            )
            .order_by(Worker.id)
        )
        return list(self.session.scalars(statement))
