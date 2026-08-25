"""Redis-backed queue primitives."""

from __future__ import annotations

from dataclasses import dataclass

from redis import Redis


@dataclass(frozen=True, slots=True)
class JobLease:
    """Details of a job temporarily owned by a worker."""

    job_id: str
    worker_id: str
    queue: str


class RedisQueue:
    """Stores ready job IDs in named Redis priority queues."""

    _QUEUE_PREFIX = "job-queue"
    _SEQUENCE_PREFIX = "job-queue-sequence"
    _LEASE_PREFIX = "job-lease"
    _SEQUENCE_SCALE = 1_000_000_000_000

    _CLAIM_SCRIPT = """
    local item = redis.call('ZPOPMIN', KEYS[1], 1)
    if #item == 0 then
        return {}
    end
    local job_id = item[1]
    local lease_key = KEYS[2] .. job_id
    if redis.call('EXISTS', lease_key) == 1 then
        redis.call('ZADD', KEYS[1], item[2], job_id)
        return {}
    end
    redis.call('HSET', lease_key, 'worker_id', ARGV[1], 'queue', ARGV[2])
    redis.call('EXPIRE', lease_key, ARGV[3])
    return {job_id, lease_key}
    """

    _RENEW_SCRIPT = """
    if redis.call('HGET', KEYS[1], 'worker_id') ~= ARGV[1] then
        return 0
    end
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
    """

    def __init__(self, client: Redis):
        self.client = client

    def enqueue(self, job_id: str, *, queue: str, priority: int = 0) -> None:
        """Add a job to a queue, ordering higher priorities first."""

        if not queue:
            raise ValueError("queue must not be empty")
        if priority < 0:
            raise ValueError("priority must not be negative")

        sequence = self.client.incr(self._sequence_key(queue))
        score = -priority * self._SEQUENCE_SCALE + sequence
        self.client.zadd(self._queue_key(queue), {job_id: score})

    def queue_size(self, queue: str) -> int:
        """Return the number of jobs currently waiting in a queue."""

        return self.client.zcard(self._queue_key(queue))

    def claim(
        self, queue: str, *, worker_id: str, lease_seconds: int = 60
    ) -> JobLease | None:
        """Atomically claim the highest-priority waiting job."""

        if not queue:
            raise ValueError("queue must not be empty")
        if not worker_id:
            raise ValueError("worker_id must not be empty")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")

        result = self.client.eval(
            self._CLAIM_SCRIPT,
            2,
            self._queue_key(queue),
            self._LEASE_PREFIX + ":",
            worker_id,
            queue,
            lease_seconds,
        )
        if not result:
            return None
        job_id, _lease_key = result
        return JobLease(job_id=job_id, worker_id=worker_id, queue=queue)

    def renew_lease(
        self, job_id: str, *, worker_id: str, lease_seconds: int = 60
    ) -> bool:
        """Renew a lease only when the caller owns it."""

        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        renewed = self.client.eval(
            self._RENEW_SCRIPT,
            1,
            self._lease_key(job_id),
            worker_id,
            lease_seconds,
        )
        return bool(renewed)

    def lease_ttl(self, job_id: str) -> int:
        """Return the remaining lease time in seconds, or -2 if absent."""

        return self.client.ttl(self._lease_key(job_id))

    def _queue_key(self, queue: str) -> str:
        return f"{self._QUEUE_PREFIX}:{queue}"

    def _sequence_key(self, queue: str) -> str:
        return f"{self._SEQUENCE_PREFIX}:{queue}"

    def _lease_key(self, job_id: str) -> str:
        return f"{self._LEASE_PREFIX}:{job_id}"
