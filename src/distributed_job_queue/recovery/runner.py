"""Worker health monitor process entry point."""

import signal
import threading
from datetime import datetime, timedelta, timezone

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.repositories import WorkerRepository


def mark_stale_workers_offline() -> list[str]:
    """Mark workers offline when their heartbeat deadline has passed."""
    settings = load_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.worker_offline_after_seconds
    )
    with SessionFactory.begin() as session:
        return WorkerRepository(session).mark_stale_offline(cutoff=cutoff)


def main() -> None:
    settings = load_settings()
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    while not stop.is_set():
        mark_stale_workers_offline()
        stop.wait(settings.worker_heartbeat_interval_seconds)


if __name__ == "__main__":
    main()
