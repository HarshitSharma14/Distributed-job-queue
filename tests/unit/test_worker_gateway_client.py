import json

import httpx
import pytest

from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.workers.gateway_client import (
    GatewayLeaseRejected,
    GatewayRequestError,
    WorkerGatewayClient,
    WorkerLease,
)


def make_client(handler) -> WorkerGatewayClient:
    return WorkerGatewayClient(
        "https://queue.example.com",
        "worker-secret",
        transport=httpx.MockTransport(handler),
    )


def test_client_registers_and_heartbeats_with_bearer_token():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/register"):
            return httpx.Response(201, json={})
        return httpx.Response(200, json={})

    client = make_client(handler)
    try:
        client.register("worker-1", ["generate_report"])
        assert client.heartbeat("worker-1") is True
    finally:
        client.close()

    assert len(requests) == 2
    assert all(
        request.headers["authorization"] == "Bearer worker-secret"
        for request in requests
    )
    assert json.loads(requests[0].content) == {
        "worker_id": "worker-1",
        "capabilities": ["generate_report"],
    }


def test_client_claims_and_parses_gateway_assignment():
    def handler(request):
        assert request.url.path == "/worker/v1/jobs/claim"
        return httpx.Response(
            200,
            json={
                "job_id": "job-1",
                "attempt_number": 2,
                "type": "generate_report",
                "queue": "reports",
                "payload": {"report_id": 42},
                "lease_token": "lease-token",
                "lease_expires_at": "2026-08-28T10:00:00+00:00",
            },
        )

    client = make_client(handler)
    try:
        claim = client.claim("reports", worker_id="worker-1", wait_seconds=20)
    finally:
        client.close()

    assert claim is not None
    assert claim.id == "job-1"
    assert claim.attempt_number == 2
    assert claim.payload == {"report_id": 42}
    assert claim.lease.worker_id == "worker-1"
    assert claim.lease.token == "lease-token"


def test_client_handles_empty_claim_and_rejected_renewal():
    responses = iter(
        [
            httpx.Response(204),
            httpx.Response(409, json={"detail": "Lease lost"}),
        ]
    )
    client = make_client(lambda _request: next(responses))
    lease = WorkerLease("job-1", "worker-1", "reports", "lease-token")
    try:
        assert client.claim("reports", worker_id="worker-1", wait_seconds=0) is None
        assert client.renew(lease) is False
    finally:
        client.close()


def test_client_reports_completion_and_failure():
    responses = iter(
        [
            httpx.Response(200, json={"status": "COMPLETED"}),
            httpx.Response(200, json={"status": "RETRY_WAIT"}),
        ]
    )
    client = make_client(lambda _request: next(responses))
    lease = WorkerLease("job-1", "worker-1", "reports", "lease-token")
    try:
        assert client.complete(lease) == JobStatus.COMPLETED
        assert client.fail(
            lease,
            error={"type": "RuntimeError", "message": "failed"},
        ) == JobStatus.RETRY_WAIT
    finally:
        client.close()


def test_client_uploads_json_result_without_worker_storage_credentials():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/result-upload"):
            return httpx.Response(
                200,
                json={
                    "job_id": "job-1",
                    "result_ref": "jobs/job-1/attempts/1/result.json",
                    "upload_url": "https://storage.example.com/signed-result",
                    "expires_at": "2026-08-28T10:05:00+00:00",
                },
            )
        if request.url.host == "storage.example.com":
            return httpx.Response(200)
        raise AssertionError(f"Unexpected request: {request.url}")

    client = make_client(handler)
    lease = WorkerLease("job-1", "worker-1", "reports", "lease-token")
    try:
        result_ref = client.store_result(lease, {"report_id": 42})
    finally:
        client.close()

    assert result_ref == "jobs/job-1/attempts/1/result.json"
    assert len(requests) == 2
    assert requests[0].headers["authorization"] == "Bearer worker-secret"
    assert "authorization" not in requests[1].headers
    assert requests[1].headers["content-type"] == "application/json"
    assert requests[1].content == b'{"report_id":42}'


def test_client_distinguishes_terminal_conflict_from_gateway_error():
    responses = iter(
        [
            httpx.Response(409, json={"detail": "Stale lease"}),
            httpx.Response(503, text="Unavailable"),
        ]
    )
    client = make_client(lambda _request: next(responses))
    lease = WorkerLease("job-1", "worker-1", "reports", "lease-token")
    try:
        with pytest.raises(GatewayLeaseRejected, match="Stale lease"):
            client.complete(lease)
        with pytest.raises(GatewayRequestError, match="503"):
            client.heartbeat("worker-1")
    finally:
        client.close()
