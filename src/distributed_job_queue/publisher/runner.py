"""Outbox publisher process entry point."""

import time
import logging

from redis import Redis

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.common.logging import configure_logging
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.publisher.service import OutboxPublisher
from distributed_job_queue.queueing import RedisQueue

logger = logging.getLogger(__name__)


def run_once() -> int:
    settings = load_settings()
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    publisher = OutboxPublisher(RedisQueue(client))
    with SessionFactory.begin() as session:
        return publisher.publish_batch(session, limit=settings.outbox_batch_size)


def main() -> None:
    settings = load_settings()
    configure_logging("outbox-publisher", debug=settings.debug)
    while True:
        published = run_once()
        if published:
            logger.info(
                "Published outbox batch",
                extra={"event": "outbox.batch_published", "count": published},
            )
        if published == 0:
            time.sleep(settings.outbox_poll_interval_seconds)


if __name__ == "__main__":
    main()
