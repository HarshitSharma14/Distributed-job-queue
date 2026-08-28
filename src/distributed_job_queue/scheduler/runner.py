"""Scheduler process that releases due retry jobs through the outbox."""

import signal
import threading
import logging
from datetime import datetime, timezone

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.common.logging import configure_logging
from distributed_job_queue.common.metrics import start_process_metrics_server
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.scheduler.service import release_due_retries

logger = logging.getLogger(__name__)


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
    configure_logging("scheduler", debug=settings.debug)
    start_process_metrics_server(settings.metrics_port)
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    while not stop.is_set():
        released = run_once()
        if released:
            logger.info(
                "Released due retries",
                extra={
                    "event": "scheduler.retries_released",
                    "count": len(released),
                    "job_ids": released,
                },
            )
        if not released:
            stop.wait(settings.scheduler_poll_interval_seconds)


if __name__ == "__main__":
    main()
