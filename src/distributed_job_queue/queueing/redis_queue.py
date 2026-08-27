"""Redis-backed ready queues and temporary in-flight claims."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from redis import Redis


@dataclass(frozen=True, slots=True)
class JobLease:
    """Details of a job temporarily owned by a worker."""

    job_id: str
    worker_id: str
    queue: str
    token: str


class RedisQueue:
    """Stores ready jobs and temporary in-flight claims in Redis."""

    _QUEUE_PREFIX = "job-queue"
    _SEQUENCE_PREFIX = "job-queue-sequence"
    _INFLIGHT_PREFIX = "job-inflight"
    _INFLIGHT_SCORE_PREFIX = "job-inflight-score"
    _LEASE_PREFIX = "job-lease"
    _NOTIFICATION_PREFIX = "job-notification"
    _SEQUENCE_SCALE = 1_000_000_000_000

    _ENQUEUE_SCRIPT = """
    local sequence = redis.call('INCR', KEYS[2])
    local score = -tonumber(ARGV[2]) * tonumber(ARGV[3]) + sequence
    local added = redis.call('ZADD', KEYS[1], 'NX', score, ARGV[1])
    if added == 1 then
        redis.call('LPUSH', KEYS[3], 'ready')
    end
    return added
    """

    _CLAIM_SCRIPT = """
    local item = redis.call('ZPOPMIN', KEYS[1], 1)
    if #item == 0 then
        return {}
    end
    local job_id = item[1]
    local original_score = item[2]
    local lease_key = KEYS[4] .. job_id
    if redis.call('EXISTS', lease_key) == 1 then
        redis.call('ZADD', KEYS[1], original_score, job_id)
        return {}
    end
    local now = redis.call('TIME')
    local deadline = tonumber(now[1]) + tonumber(ARGV[4])
    redis.call('ZADD', KEYS[2], deadline, job_id)
    redis.call('HSET', KEYS[3], job_id, original_score)
    redis.call('HSET', lease_key, 'worker_id', ARGV[1], 'queue', ARGV[2], 'token', ARGV[3])
    redis.call('EXPIRE', lease_key, ARGV[4])
    if ARGV[5] == '1' then
        redis.call('LPOP', KEYS[5])
    end
    return {job_id, lease_key}
    """

    _RENEW_SCRIPT = """
    if redis.call('HGET', KEYS[1], 'worker_id') ~= ARGV[1]
       or redis.call('HGET', KEYS[1], 'token') ~= ARGV[2] then
        return 0
    end
    local now = redis.call('TIME')
    local deadline = tonumber(now[1]) + tonumber(ARGV[3])
    redis.call('EXPIRE', KEYS[1], ARGV[3])
    redis.call('ZADD', KEYS[2], deadline, ARGV[4])
    return 1
    """

    _RELEASE_SCRIPT = """
    if redis.call('HGET', KEYS[1], 'worker_id') ~= ARGV[1]
       or redis.call('HGET', KEYS[1], 'token') ~= ARGV[2] then
        return 0
    end
    redis.call('DEL', KEYS[1])
    redis.call('ZREM', KEYS[2], ARGV[3])
    redis.call('HDEL', KEYS[3], ARGV[3])
    return 1
    """

    _ABANDON_SCRIPT = """
    if redis.call('HGET', KEYS[1], 'worker_id') ~= ARGV[1]
       or redis.call('HGET', KEYS[1], 'token') ~= ARGV[2] then
        return 0
    end
    local original_score = redis.call('HGET', KEYS[4], ARGV[3])
    if original_score then
        local added = redis.call('ZADD', KEYS[2], 'NX', original_score, ARGV[3])
        if added == 1 then
            redis.call('LPUSH', KEYS[5], 'ready')
        end
    end
    redis.call('DEL', KEYS[1])
    redis.call('ZREM', KEYS[3], ARGV[3])
    redis.call('HDEL', KEYS[4], ARGV[3])
    return 1
    """

    _REQUEUE_EXPIRED_SCRIPT = """
    local now = redis.call('TIME')
    local jobs = redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', now[1], 'LIMIT', 0, ARGV[1])
    local requeued = {}
    for _, job_id in ipairs(jobs) do
        local original_score = redis.call('HGET', KEYS[3], job_id)
        if original_score then
            local added = redis.call('ZADD', KEYS[1], 'NX', original_score, job_id)
            if added == 1 then
                redis.call('LPUSH', KEYS[5], 'ready')
                table.insert(requeued, job_id)
            end
        end
        redis.call('ZREM', KEYS[2], job_id)
        redis.call('HDEL', KEYS[3], job_id)
        redis.call('DEL', KEYS[4] .. job_id)
    end
    return requeued
    """

    def __init__(self, client: Redis):
        self.client = client

    def enqueue(self, job_id: str, *, queue: str, priority: int = 0) -> bool:
        """Add a job once, preserving its original position on retries."""

        if not queue:
            raise ValueError("queue must not be empty")
        if priority < 0:
            raise ValueError("priority must not be negative")
        return bool(
            self.client.eval(
                self._ENQUEUE_SCRIPT,
                3,
                self._queue_key(queue),
                self._sequence_key(queue),
                self._notification_key(queue),
                job_id,
                priority,
                self._SEQUENCE_SCALE,
            )
        )

    def queue_size(self, queue: str) -> int:
        return self.client.zcard(self._queue_key(queue))

    def inflight_size(self, queue: str) -> int:
        return self.client.zcard(self._inflight_key(queue))

    def claim(
        self,
        queue: str,
        *,
        worker_id: str,
        lease_seconds: int = 60,
        notification_consumed: bool = False,
    ) -> JobLease | None:
        """Atomically move the highest-priority job from ready to in-flight."""

        if not queue:
            raise ValueError("queue must not be empty")
        if not worker_id:
            raise ValueError("worker_id must not be empty")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        token = str(uuid.uuid4())
        result = self.client.eval(
            self._CLAIM_SCRIPT,
            5,
            self._queue_key(queue),
            self._inflight_key(queue),
            self._inflight_score_key(queue),
            self._LEASE_PREFIX + ":",
            self._notification_key(queue),
            worker_id,
            queue,
            token,
            lease_seconds,
            "0" if notification_consumed else "1",
        )
        if not result:
            return None
        job_id, _lease_key = result
        return JobLease(job_id=job_id, worker_id=worker_id, queue=queue, token=token)

    def long_poll(
        self,
        queue: str,
        *,
        worker_id: str,
        lease_seconds: int = 60,
        wait_seconds: int = 20,
    ) -> JobLease | None:
        """Block in Redis until work arrives or the bounded timeout expires."""

        if wait_seconds < 0:
            raise ValueError("wait_seconds must not be negative")

        lease = self.claim(queue, worker_id=worker_id, lease_seconds=lease_seconds)
        if lease is not None or wait_seconds == 0:
            return lease

        deadline = time.monotonic() + wait_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            notification = self.client.brpop(
                self._notification_key(queue), timeout=remaining
            )
            if notification is None:
                return None
            lease = self.claim(
                queue,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                notification_consumed=True,
            )
            if lease is not None:
                return lease

    def renew_lease(
        self,
        job_id: str,
        *,
        queue: str,
        worker_id: str,
        token: str,
        lease_seconds: int = 60,
    ) -> bool:
        """Renew a temporary lease only when the fencing token matches."""

        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        renewed = self.client.eval(
            self._RENEW_SCRIPT,
            2,
            self._lease_key(job_id),
            self._inflight_key(queue),
            worker_id,
            token,
            lease_seconds,
            job_id,
        )
        return bool(renewed)

    def release_lease(
        self, job_id: str, *, queue: str, worker_id: str, token: str
    ) -> bool:
        """Remove a completed claim without returning it to ready."""

        released = self.client.eval(
            self._RELEASE_SCRIPT,
            3,
            self._lease_key(job_id),
            self._inflight_key(queue),
            self._inflight_score_key(queue),
            worker_id,
            token,
            job_id,
        )
        return bool(released)

    def abandon_claim(
        self, job_id: str, *, queue: str, worker_id: str, token: str
    ) -> bool:
        """Return a claim to ready when its PostgreSQL handoff fails."""

        abandoned = self.client.eval(
            self._ABANDON_SCRIPT,
            5,
            self._lease_key(job_id),
            self._queue_key(queue),
            self._inflight_key(queue),
            self._inflight_score_key(queue),
            self._notification_key(queue),
            worker_id,
            token,
            job_id,
        )
        return bool(abandoned)

    def requeue_expired(self, queue: str, *, limit: int = 100) -> list[str]:
        """Return timed-out in-flight claims to their original ready queue."""

        if limit < 1:
            raise ValueError("limit must be at least 1")
        return list(
            self.client.eval(
                self._REQUEUE_EXPIRED_SCRIPT,
                5,
                self._queue_key(queue),
                self._inflight_key(queue),
                self._inflight_score_key(queue),
                self._LEASE_PREFIX + ":",
                self._notification_key(queue),
                limit,
            )
        )

    def lease_ttl(self, job_id: str) -> int:
        return self.client.ttl(self._lease_key(job_id))

    def _queue_key(self, queue: str) -> str:
        return f"{self._QUEUE_PREFIX}:{queue}"

    def _sequence_key(self, queue: str) -> str:
        return f"{self._SEQUENCE_PREFIX}:{queue}"

    def _inflight_key(self, queue: str) -> str:
        return f"{self._INFLIGHT_PREFIX}:{queue}"

    def _inflight_score_key(self, queue: str) -> str:
        return f"{self._INFLIGHT_SCORE_PREFIX}:{queue}"

    def _lease_key(self, job_id: str) -> str:
        return f"{self._LEASE_PREFIX}:{job_id}"

    def _notification_key(self, queue: str) -> str:
        return f"{self._NOTIFICATION_PREFIX}:{queue}"
