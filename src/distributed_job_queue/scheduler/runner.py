"""Scheduler process that releases due retry jobs through the outbox."""

import signal
import threading
from datetime import datetime, timezone

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.scheduler.service import release_due_retries


def run_once() -> list[str]:
    settings = load_settings()
    with SessionFactory.begin() as session:
        return release_due_retries(
            session,
            now=datetime.now(timezone.utc),
            limit=settings.scheduler_batch_size,
        )


def main() -> None:
    settings = load_settings()
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    while not stop.is_set():
        released = run_once()
        if not released:
            stop.wait(settings.scheduler_poll_interval_seconds)


if __name__ == "__main__":
    main()
