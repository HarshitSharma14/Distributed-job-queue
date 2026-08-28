"""Worker-health and expired-job-lease recovery process."""

import signal
import threading
import logging
from datetime import datetime, timezone

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.common.logging import configure_logging
from distributed_job_queue.common.metrics import start_process_metrics_server
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.recovery.service import RecoveryResult, recover_stale_work

logger = logging.getLogger(__name__)


def run_once() -> RecoveryResult:
    """Recover one transactional batch from authoritative PostgreSQL state."""

    settings = load_settings()
    with SessionFactory.begin() as session:
        return recover_stale_work(
            session,
            now=datetime.now(timezone.utc),
            worker_offline_after_seconds=settings.worker_offline_after_seconds,
            retry_base_delay_seconds=settings.retry_base_delay_seconds,
            retry_max_delay_seconds=settings.retry_max_delay_seconds,
            limit=settings.recovery_batch_size,
        )


def main() -> None:
    settings = load_settings()
    configure_logging("recovery", debug=settings.debug)
    start_process_metrics_server(settings.metrics_port)
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    while not stop.is_set():
        result = run_once()
        if result.offline_worker_ids or result.recovered_job_ids:
            logger.warning(
                "Recovered stale distributed state",
                extra={
                    "event": "recovery.batch_completed",
                    "offline_worker_ids": result.offline_worker_ids,
                    "recovered_job_ids": result.recovered_job_ids,
                },
            )
        if not result.offline_worker_ids and not result.recovered_job_ids:
            stop.wait(settings.recovery_poll_interval_seconds)


if __name__ == "__main__":
    main()
