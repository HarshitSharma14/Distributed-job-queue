import threading
from types import SimpleNamespace

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.workers.runner import consume_loop, heartbeat_loop


def test_heartbeat_stops_when_registered_agent_disappears():
    stop = threading.Event()

    heartbeat_loop(
        stop,
        worker_id="worker-1",
        interval_seconds=0.001,
        heartbeat=lambda worker_id: False,
    )

    assert stop.is_set()


def test_consume_loop_rotates_queues_and_executes_claimed_job():
    stop = threading.Event()
    claimed = SimpleNamespace(id="job-1")

    class Consumer:
        def __init__(self):
            self.queues = []

        def claim_next(self, queue_name, **_kwargs):
            self.queues.append(queue_name)
            return claimed if queue_name == "images" else None

    class Executor:
        def execute(self, received):
            assert received is claimed
            stop.set()
            return SimpleNamespace(status=JobStatus.COMPLETED)

    consumer = Consumer()
    consume_loop(
        stop,
        worker_id="worker-1",
        queue_names=["reports", "images"],
        consumer=consumer,
        executor=Executor(),
        wait_seconds=0,
    )

    assert consumer.queues == ["reports", "images"]
