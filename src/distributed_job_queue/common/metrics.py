"""Low-cardinality Prometheus metrics shared by platform processes."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from prometheus_client import (
    REGISTRY,
    Counter,
    Histogram,
    disable_created_metrics,
    start_http_server,
)
from prometheus_client.core import GaugeMetricFamily
from redis import Redis
from sqlalchemy import func, select

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.models import Job, Worker
from distributed_job_queue.queueing import RedisQueue

logger = logging.getLogger(__name__)
disable_created_metrics()

HTTP_REQUESTS = Counter(
    "djq_http_requests_total",
    "HTTP requests handled by method, route template, and status code.",
    ("method", "route", "status_code"),
)
HTTP_DURATION = Histogram(
    "djq_http_request_duration_seconds",
    "HTTP request latency by method and route template.",
    ("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 15, 30),
)
JOBS_SUBMITTED = Counter(
    "djq_jobs_submitted_total",
    "Durable non-replayed jobs submitted by queue.",
    ("queue",),
)
JOB_ATTEMPTS_STARTED = Counter(
    "djq_job_attempts_started_total",
    "Job attempts durably started by queue.",
    ("queue",),
)
JOB_ATTEMPTS_FINISHED = Counter(
    "djq_job_attempts_finished_total",
    "Job attempts finished by queue and resulting job state.",
    ("queue", "outcome"),
)
JOB_QUEUE_WAIT = Histogram(
    "djq_job_queue_wait_seconds",
    "Time from durable job creation until an attempt starts.",
    ("queue",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300, 900),
)
JOB_EXECUTION_DURATION = Histogram(
    "djq_job_execution_duration_seconds",
    "Duration of finished job attempts by queue and outcome.",
    ("queue", "outcome"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300, 900, 3600),
)
LEASE_LOSSES = Counter(
    "djq_lease_losses_total",
    "Worker operations rejected because the active lease was lost.",
    ("operation",),
)
OUTBOX_PUBLISHED = Counter(
    "djq_outbox_events_published_total",
    "Job-ready outbox events published by queue.",
    ("queue",),
)
SCHEDULER_RELEASED = Counter(
    "djq_scheduler_jobs_released_total",
    "Retry-wait jobs released by the scheduler.",
)
RECOVERED_JOBS = Counter(
    "djq_recovered_jobs_total",
    "Expired running jobs recovered by resulting state.",
    ("outcome",),
)
WORKERS_MARKED_OFFLINE = Counter(
    "djq_workers_marked_offline_total",
    "Stale workers marked offline by recovery.",
)


class PlatformStateCollector:
    """Collect authoritative current state from PostgreSQL and Redis."""

    def describe(self) -> Iterable[GaugeMetricFamily]:
        return ()

    def collect(self) -> Iterable[GaugeMetricFamily]:
        job_states = GaugeMetricFamily(
            "djq_jobs",
            "Current durable jobs by state.",
            labels=("status",),
        )
        worker_states = GaugeMetricFamily(
            "djq_workers",
            "Current registered workers by state.",
            labels=("status",),
        )
        queue_depth = GaugeMetricFamily(
            "djq_queue_depth",
            "Current Redis ready-job depth by queue.",
            labels=("queue",),
        )
        collector_up = GaugeMetricFamily(
            "djq_state_collector_up",
            "Whether current-state collection succeeded by source.",
            labels=("source",),
        )

        queue_names: list[str] = []
        try:
            with SessionFactory() as session:
                for status, count in session.execute(
                    select(Job.status, func.count()).group_by(Job.status)
                ):
                    job_states.add_metric((status,), count)
                for status, count in session.execute(
                    select(Worker.status, func.count()).group_by(Worker.status)
                ):
                    worker_states.add_metric((status,), count)
                queue_names = list(
                    session.scalars(select(Job.queue).distinct().order_by(Job.queue))
                )
            collector_up.add_metric(("postgresql",), 1)
        except Exception:
            logger.exception(
                "PostgreSQL metric collection failed",
                extra={"event": "metrics.collection_failed", "source": "postgresql"},
            )
            collector_up.add_metric(("postgresql",), 0)

        client: Redis | None = None
        try:
            client = Redis.from_url(load_settings().redis_url, decode_responses=True)
            queue = RedisQueue(client)
            for queue_name in queue_names:
                queue_depth.add_metric((queue_name,), queue.queue_size(queue_name))
            collector_up.add_metric(("redis",), 1)
        except Exception:
            logger.exception(
                "Redis metric collection failed",
                extra={"event": "metrics.collection_failed", "source": "redis"},
            )
            collector_up.add_metric(("redis",), 0)
        finally:
            if client is not None:
                client.close()

        yield job_states
        yield worker_states
        yield queue_depth
        yield collector_up


def start_process_metrics_server(port: int) -> None:
    """Expose one long-running non-API process on an internal metrics port."""

    if port > 0:
        start_http_server(port)


_state_collector_registered = False


def register_platform_state_collector() -> None:
    """Make one API target authoritative for current-state gauges."""

    global _state_collector_registered
    if not _state_collector_registered:
        REGISTRY.register(PlatformStateCollector())
        _state_collector_registered = True
