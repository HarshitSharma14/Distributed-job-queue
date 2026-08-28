"""Executable worker process lifecycle."""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from collections.abc import Callable

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.common.logging import configure_logging
from distributed_job_queue.workers.consumer import WorkerConsumer
from distributed_job_queue.workers.executor import LeaseLost, WorkerExecutor
from distributed_job_queue.workers.gateway_client import WorkerGatewayClient
from distributed_job_queue.workers.handlers import (
    HandlerRegistry,
    UnknownJobHandler,
    load_handler_modules,
)
from distributed_job_queue.workers.runtime import create_worker_id

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a distributed job worker")
    parser.add_argument("--name", help="Stable ID for this worker process")
    parser.add_argument(
        "--queue",
        action="append",
        default=[],
        help="Queue to consume; may be provided more than once",
    )
    parser.add_argument(
        "--capability",
        action="append",
        default=[],
        help="Advertised capability; defaults to registered job types",
    )
    parser.add_argument(
        "--handler-module",
        action="append",
        required=True,
        help="Module exposing register_handlers(registry); may be repeated",
    )
    return parser.parse_args()


def heartbeat_loop(
    stop: threading.Event,
    *,
    worker_id: str,
    capabilities: list[str],
    interval_seconds: float,
    heartbeat: Callable[[str], bool],
    register: Callable[[str, list[str]], None],
) -> None:
    """Maintain worker presence independently of polling and execution."""

    while not stop.wait(interval_seconds):
        try:
            if not heartbeat(worker_id):
                register(worker_id, capabilities)
        except Exception:
            logger.exception(
                "Worker heartbeat failed",
                extra={
                    "event": "worker.heartbeat_failed",
                    "worker_id": worker_id,
                },
            )


def consume_loop(
    stop: threading.Event,
    *,
    worker_id: str,
    queue_names: list[str],
    consumer: WorkerConsumer,
    executor: WorkerExecutor,
    wait_seconds: int,
) -> None:
    """Consume subscribed queues until a shutdown signal is received."""

    if not queue_names:
        raise ValueError("At least one queue subscription is required")
    per_queue_wait = (
        0 if wait_seconds == 0 else max(1, wait_seconds // len(queue_names))
    )
    while not stop.is_set():
        for queue_name in queue_names:
            if stop.is_set():
                return
            try:
                claimed = consumer.claim_next(
                    queue_name,
                    worker_id=worker_id,
                    wait_seconds=per_queue_wait,
                )
                if claimed is not None:
                    outcome = executor.execute(claimed)
                    logger.info(
                        "Job attempt finished",
                        extra={
                            "event": "job.execution_finished",
                            "job_id": claimed.id,
                            "worker_id": worker_id,
                            "status": outcome.status.value,
                        },
                    )
            except UnknownJobHandler:
                logger.exception(
                    "Worker does not support claimed job type",
                    extra={
                        "event": "worker.unsupported_job_type",
                        "worker_id": worker_id,
                        "queue": queue_name,
                    },
                )
                stop.wait(1)
            except LeaseLost:
                logger.exception(
                    "Worker lost job ownership during execution",
                    extra={
                        "event": "job.lease_lost",
                        "worker_id": worker_id,
                        "queue": queue_name,
                    },
                )
            except Exception:
                logger.exception(
                    "Worker iteration failed",
                    extra={
                        "event": "worker.iteration_failed",
                        "worker_id": worker_id,
                        "queue": queue_name,
                    },
                )
                stop.wait(1)


def main() -> None:
    args = parse_args()
    settings = load_settings()
    configure_logging(
        "worker",
        debug=settings.debug,
        secrets=(settings.worker_gateway_token,),
    )

    registry = HandlerRegistry()
    load_handler_modules(registry, args.handler_module)
    worker_id = create_worker_id(args.name)
    queue_names = args.queue or ["default"]
    capabilities = args.capability or list(registry.job_types())
    if not capabilities:
        raise SystemExit("No handlers or worker capabilities were registered")

    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    gateway = WorkerGatewayClient(
        settings.worker_gateway_url,
        settings.worker_gateway_token,
    )
    consumer = WorkerConsumer(gateway, registry)
    executor = WorkerExecutor(
        gateway,
        lease_seconds=settings.job_lease_seconds,
    )

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        kwargs={
            "stop": stop,
            "worker_id": worker_id,
            "capabilities": capabilities,
            "interval_seconds": settings.worker_heartbeat_interval_seconds,
            "heartbeat": gateway.heartbeat,
            "register": gateway.register,
        },
        name=f"heartbeat-{worker_id}",
        daemon=True,
    )
    heartbeat_started = False
    try:
        gateway.register(worker_id, capabilities)
        heartbeat_thread.start()
        heartbeat_started = True
        consume_loop(
            stop,
            worker_id=worker_id,
            queue_names=queue_names,
            consumer=consumer,
            executor=executor,
            wait_seconds=settings.worker_long_poll_seconds,
        )
    finally:
        stop.set()
        if heartbeat_started:
            heartbeat_thread.join()
        gateway.close()


if __name__ == "__main__":
    main()
