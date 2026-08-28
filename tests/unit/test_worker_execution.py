import time
from datetime import datetime, timezone

import pytest

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.workers import (
    GatewayClaim,
    GatewayLeaseRejected,
    HandlerRegistry,
    LeaseLost,
    WorkerConsumer,
    WorkerExecutor,
    WorkerLease,
)


class FakeGateway:
    def __init__(self, claim: GatewayClaim | None = None) -> None:
        self.claim_result = claim
        self.claim_calls = []
        self.renew_calls = []
        self.complete_calls = []
        self.fail_calls = []
        self.renew_result = True
        self.complete_status = JobStatus.COMPLETED
        self.fail_status = JobStatus.RETRY_WAIT
        self.reject_completion = False

    def claim(self, queue, *, worker_id, wait_seconds):
        self.claim_calls.append((queue, worker_id, wait_seconds))
        return self.claim_result

    def renew(self, lease):
        self.renew_calls.append(lease)
        return self.renew_result

    def complete(self, lease, *, result_ref=None):
        self.complete_calls.append((lease, result_ref))
        if self.reject_completion:
            raise GatewayLeaseRejected("stale lease")
        return self.complete_status

    def fail(self, lease, *, error):
        self.fail_calls.append((lease, error))
        return self.fail_status


def make_claim() -> GatewayClaim:
    return GatewayClaim(
        id="job-1",
        attempt_number=1,
        type="generate_report",
        payload={"report_id": 42},
        lease=WorkerLease(
            job_id="job-1",
            worker_id="worker-1",
            queue="reports",
            token="lease-token",
        ),
        lease_expires_at=datetime.now(timezone.utc),
    )


def test_consumer_claims_through_gateway_and_attaches_handler():
    gateway = FakeGateway(make_claim())
    registry = HandlerRegistry()
    registry.register("generate_report", lambda payload: payload["report_id"])

    claimed = WorkerConsumer(gateway, registry).claim_next(
        "reports",
        worker_id="worker-1",
        wait_seconds=20,
    )

    assert claimed is not None
    assert claimed.id == "job-1"
    assert claimed.handler(claimed.payload) == 42
    assert gateway.claim_calls == [("reports", "worker-1", 20)]


def test_executor_reports_success_through_gateway():
    gateway = FakeGateway(make_claim())
    registry = HandlerRegistry()
    registry.register("generate_report", lambda payload: payload["report_id"])
    claimed = WorkerConsumer(gateway, registry).claim_next(
        "reports", worker_id="worker-1", wait_seconds=0
    )
    assert claimed is not None

    outcome = WorkerExecutor(gateway, lease_seconds=60).execute(claimed)

    assert outcome.status == JobStatus.COMPLETED
    assert outcome.result == 42
    assert gateway.complete_calls == [(claimed.lease, None)]
    assert gateway.fail_calls == []


def test_executor_reports_handler_failure_through_gateway():
    gateway = FakeGateway(make_claim())
    registry = HandlerRegistry()

    def fail_handler(_payload):
        raise RuntimeError("report service unavailable")

    registry.register("generate_report", fail_handler)
    claimed = WorkerConsumer(gateway, registry).claim_next(
        "reports", worker_id="worker-1", wait_seconds=0
    )
    assert claimed is not None

    outcome = WorkerExecutor(gateway, lease_seconds=60).execute(claimed)

    assert outcome.status == JobStatus.RETRY_WAIT
    assert outcome.error == {
        "type": "RuntimeError",
        "message": "report service unavailable",
    }
    assert gateway.fail_calls == [(claimed.lease, outcome.error)]


def test_executor_renews_slow_job_through_gateway():
    gateway = FakeGateway(make_claim())
    registry = HandlerRegistry()

    def slow_handler(payload):
        time.sleep(0.04)
        return payload["report_id"]

    registry.register("generate_report", slow_handler)
    claimed = WorkerConsumer(gateway, registry).claim_next(
        "reports", worker_id="worker-1", wait_seconds=0
    )
    assert claimed is not None

    outcome = WorkerExecutor(
        gateway,
        lease_seconds=1,
        renewal_interval_seconds=0.01,
    ).execute(claimed)

    assert outcome.status == JobStatus.COMPLETED
    assert len(gateway.renew_calls) >= 1


def test_executor_stops_when_gateway_rejects_renewal():
    gateway = FakeGateway(make_claim())
    gateway.renew_result = False
    registry = HandlerRegistry()

    def slow_handler(payload):
        time.sleep(0.04)
        return payload["report_id"]

    registry.register("generate_report", slow_handler)
    claimed = WorkerConsumer(gateway, registry).claim_next(
        "reports", worker_id="worker-1", wait_seconds=0
    )
    assert claimed is not None

    with pytest.raises(LeaseLost, match="job-1"):
        WorkerExecutor(
            gateway,
            lease_seconds=1,
            renewal_interval_seconds=0.01,
        ).execute(claimed)

    assert gateway.complete_calls == []


def test_executor_translates_stale_completion_to_lease_loss():
    gateway = FakeGateway(make_claim())
    gateway.reject_completion = True
    registry = HandlerRegistry()
    registry.register("generate_report", lambda payload: payload["report_id"])
    claimed = WorkerConsumer(gateway, registry).claim_next(
        "reports", worker_id="worker-1", wait_seconds=0
    )
    assert claimed is not None

    with pytest.raises(LeaseLost, match="job-1"):
        WorkerExecutor(gateway, lease_seconds=60).execute(claimed)
