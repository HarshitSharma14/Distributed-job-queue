import pytest
from redis import Redis

from distributed_job_queue.common.config import load_settings
from distributed_job_queue.queueing import RedisQueue


@pytest.fixture
def redis_queue():
    client = Redis.from_url(load_settings().redis_url, decode_responses=True)
    queue_name = "integration-test"
    client.delete(
        f"job-queue:{queue_name}",
        f"job-queue-sequence:{queue_name}",
        "job-lease:high",
        "job-lease:job-1",
    )
    yield RedisQueue(client), client, queue_name
    client.delete(
        f"job-queue:{queue_name}",
        f"job-queue-sequence:{queue_name}",
        "job-lease:high",
        "job-lease:job-1",
    )


def test_enqueue_adds_job_to_named_queue(redis_queue):
    queue, _, queue_name = redis_queue

    queue.enqueue("job-1", queue=queue_name, priority=3)

    assert queue.queue_size(queue_name) == 1


def test_enqueue_rejects_invalid_values(redis_queue):
    queue, _, queue_name = redis_queue

    with pytest.raises(ValueError, match="queue"):
        queue.enqueue("job-1", queue="", priority=1)
    with pytest.raises(ValueError, match="priority"):
        queue.enqueue("job-2", queue=queue_name, priority=-1)


def test_claim_returns_highest_priority_and_creates_lease(redis_queue):
    queue, client, queue_name = redis_queue
    queue.enqueue("low", queue=queue_name, priority=1)
    queue.enqueue("high", queue=queue_name, priority=10)

    lease = queue.claim(queue_name, worker_id="worker-1", lease_seconds=30)

    assert lease is not None
    assert lease.job_id == "high"
    assert lease.worker_id == "worker-1"
    assert queue.queue_size(queue_name) == 1
    assert client.ttl("job-lease:high") > 0


def test_only_one_worker_can_claim_a_job(redis_queue):
    queue, _, queue_name = redis_queue
    queue.enqueue("job-1", queue=queue_name)

    first = queue.claim(queue_name, worker_id="worker-1")
    second = queue.claim(queue_name, worker_id="worker-2")

    assert first is not None
    assert second is None


def test_only_lease_owner_can_renew(redis_queue):
    queue, _, queue_name = redis_queue
    queue.enqueue("job-1", queue=queue_name)
    queue.claim(queue_name, worker_id="worker-1", lease_seconds=10)

    assert queue.renew_lease("job-1", worker_id="worker-2") is False
    assert queue.renew_lease("job-1", worker_id="worker-1", lease_seconds=30) is True
