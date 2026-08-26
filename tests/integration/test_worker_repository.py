from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from distributed_job_queue.domain.worker import WorkerStatus
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.repositories import WorkerRepository


@pytest.fixture
def worker_repository():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield WorkerRepository(session)
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_register_and_reconnect_worker(worker_repository):
    now = datetime.now(timezone.utc)
    worker = worker_repository.register(
        "worker-1", capabilities=["reports", "reports"], now=now
    )
    assert worker.status == WorkerStatus.ONLINE.value
    assert worker.capabilities == ["reports"]

    reconnected = worker_repository.register(
        "worker-1", capabilities=["images"], now=now + timedelta(seconds=5)
    )
    assert reconnected.capabilities == ["images"]
    assert reconnected.status == WorkerStatus.ONLINE.value


def test_heartbeat_restores_worker_online(worker_repository):
    now = datetime.now(timezone.utc)
    worker_repository.register("worker-1", capabilities=["default"], now=now)
    worker_repository.mark_offline("worker-1")

    assert worker_repository.heartbeat(
        "worker-1", now=now + timedelta(seconds=10)
    ) is True
    online = worker_repository.list_by_status(WorkerStatus.ONLINE)
    assert [worker.id for worker in online] == ["worker-1"]


def test_stale_workers_are_marked_offline(worker_repository):
    now = datetime.now(timezone.utc)
    worker_repository.register(
        "stale-worker", capabilities=["reports"], now=now - timedelta(minutes=2)
    )
    worker_repository.register("healthy-worker", capabilities=["reports"], now=now)

    stale_ids = worker_repository.mark_stale_offline(
        cutoff=now - timedelta(seconds=60)
    )

    assert stale_ids == ["stale-worker"]
    report_workers = worker_repository.list_by_capability("reports")
    assert [worker.id for worker in report_workers] == ["healthy-worker"]
