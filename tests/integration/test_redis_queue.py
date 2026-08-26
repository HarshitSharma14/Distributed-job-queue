import pytest
from redis import Redis

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.queueing import RedisQueue


@pytest.fixture
def redis_queue():
    client = Redis.from_url(load_settings().redis_url, decode_responses=True)
    queue_name = "integration-test"
    keys = [
        f"job-queue:{queue_name}",
        f"job-queue-sequence:{queue_name}",
        f"job-inflight:{queue_name}",
        f"job-inflight-score:{queue_name}",
        "job-lease:high",
        "job-lease:job-1",
        "job-lease:job-expired",
    ]
    client.delete(*keys)
    yield RedisQueue(client), client, queue_name
    client.delete(*keys)


def test_enqueue_is_idempotent(redis_queue):
    queue, client, queue_name = redis_queue

    assert queue.enqueue("job-1", queue=queue_name, priority=3) is True
    original_score = client.zscore(f"job-queue:{queue_name}", "job-1")
    assert queue.enqueue("job-1", queue=queue_name, priority=10) is False

    assert queue.queue_size(queue_name) == 1
    assert client.zscore(f"job-queue:{queue_name}", "job-1") == original_score


def test_enqueue_rejects_invalid_values(redis_queue):
    queue, _, queue_name = redis_queue

    with pytest.raises(ValueError, match="queue"):
        queue.enqueue("job-1", queue="", priority=1)
    with pytest.raises(ValueError, match="priority"):
        queue.enqueue("job-2", queue=queue_name, priority=-1)


def test_claim_moves_highest_priority_job_to_inflight(redis_queue):
    queue, client, queue_name = redis_queue
    queue.enqueue("low", queue=queue_name, priority=1)
    queue.enqueue("high", queue=queue_name, priority=10)

    lease = queue.claim(queue_name, worker_id="worker-1", lease_seconds=30)

    assert lease is not None
    assert lease.job_id == "high"
    assert lease.token
    assert queue.queue_size(queue_name) == 1
    assert queue.inflight_size(queue_name) == 1
    assert client.ttl("job-lease:high") > 0


def test_only_lease_owner_can_renew(redis_queue):
    queue, _, queue_name = redis_queue
    queue.enqueue("job-1", queue=queue_name)
    lease = queue.claim(queue_name, worker_id="worker-1", lease_seconds=10)
    assert lease is not None

    assert queue.renew_lease(
        "job-1", queue=queue_name, worker_id="worker-2", token=lease.token
    ) is False
    assert queue.renew_lease(
        "job-1", queue=queue_name, worker_id="worker-1", token="stale-token"
    ) is False
    assert queue.renew_lease(
        "job-1",
        queue=queue_name,
        worker_id="worker-1",
        token=lease.token,
        lease_seconds=30,
    ) is True


def test_abandon_claim_returns_job_to_ready(redis_queue):
    queue, _, queue_name = redis_queue
    queue.enqueue("job-1", queue=queue_name, priority=4)
    lease = queue.claim(queue_name, worker_id="worker-1")
    assert lease is not None

    assert queue.abandon_claim(
        "job-1", queue=queue_name, worker_id="worker-1", token=lease.token
    ) is True
    assert queue.queue_size(queue_name) == 1
    assert queue.inflight_size(queue_name) == 0


def test_expired_inflight_claim_returns_to_ready(redis_queue):
    queue, client, queue_name = redis_queue
    queue.enqueue("job-expired", queue=queue_name, priority=4)
    lease = queue.claim(queue_name, worker_id="worker-1", lease_seconds=30)
    assert lease is not None
    client.zadd(f"job-inflight:{queue_name}", {"job-expired": 0})

    assert queue.requeue_expired(queue_name) == ["job-expired"]
    assert queue.queue_size(queue_name) == 1
    assert queue.inflight_size(queue_name) == 0
    assert queue.lease_ttl("job-expired") == -2


def test_release_removes_completed_claim(redis_queue):
    queue, _, queue_name = redis_queue
    queue.enqueue("job-1", queue=queue_name)
    lease = queue.claim(queue_name, worker_id="worker-1")
    assert lease is not None

    assert queue.release_lease(
        "job-1", queue=queue_name, worker_id="worker-1", token="stale-token"
    ) is False
    assert queue.release_lease(
        "job-1", queue=queue_name, worker_id="worker-1", token=lease.token
    ) is True
    assert queue.queue_size(queue_name) == 0
    assert queue.inflight_size(queue_name) == 0
