"""Worker process entry point."""

import argparse
import signal
import threading

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.workers.runtime import (
    create_worker_id,
    heartbeat_worker,
    mark_worker_offline,
    register_worker,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a distributed job worker")
    parser.add_argument("--name", help="Stable ID for this worker process")
    parser.add_argument(
        "--capability",
        action="append",
        default=[],
        help="Queue capability; may be provided more than once",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    worker_id = create_worker_id(args.name)
    capabilities = args.capability or ["default"]
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    register_worker(worker_id, capabilities)
    try:
        while not stop.wait(settings.worker_heartbeat_interval_seconds):
            if not heartbeat_worker(worker_id):
                register_worker(worker_id, capabilities)
    finally:
        mark_worker_offline(worker_id)


if __name__ == "__main__":
    main()
