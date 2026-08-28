"""HTTP-only client used by external worker execution agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from distributed_job_queue.domain.job import JobStatus


class GatewayRequestError(RuntimeError):
    """Raised when the Worker Gateway rejects or cannot process a request."""


class GatewayLeaseRejected(GatewayRequestError):
    """Raised when a terminal report no longer owns the job attempt."""


@dataclass(frozen=True, slots=True)
class WorkerLease:
    job_id: str
    worker_id: str
    queue: str
    token: str


@dataclass(frozen=True, slots=True)
class GatewayClaim:
    id: str
    attempt_number: int
    type: str
    payload: dict[str, Any]
    lease: WorkerLease
    lease_expires_at: datetime


class WorkerGatewayClient:
    """Expose worker operations without infrastructure credentials."""

    def __init__(
        self,
        api_url: str,
        token: str,
        *,
        request_timeout_seconds: float = 10,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_url:
            raise ValueError("api_url must not be empty")
        if not token:
            raise ValueError("token must not be empty")
        self.request_timeout_seconds = request_timeout_seconds
        self._client = httpx.Client(
            base_url=api_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=request_timeout_seconds,
            transport=transport,
        )
        self._upload_client = httpx.Client(
            timeout=request_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()
        self._upload_client.close()

    def register(self, worker_id: str, capabilities: list[str]) -> None:
        response = self._client.post(
            "/worker/v1/workers/register",
            json={"worker_id": worker_id, "capabilities": capabilities},
        )
        self._raise_for_gateway_error(response)

    def heartbeat(self, worker_id: str) -> bool:
        response = self._client.post(
            f"/worker/v1/workers/{worker_id}/heartbeat"
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return False
        self._raise_for_gateway_error(response)
        return True

    def claim(
        self,
        queue: str,
        *,
        worker_id: str,
        wait_seconds: int,
    ) -> GatewayClaim | None:
        response = self._client.post(
            "/worker/v1/jobs/claim",
            json={
                "worker_id": worker_id,
                "queue": queue,
                "wait_seconds": wait_seconds,
            },
            timeout=max(self.request_timeout_seconds, wait_seconds + 5),
        )
        if response.status_code == httpx.codes.NO_CONTENT:
            return None
        self._raise_for_gateway_error(response)
        body = response.json()
        return GatewayClaim(
            id=body["job_id"],
            attempt_number=body["attempt_number"],
            type=body["type"],
            payload=body["payload"],
            lease=WorkerLease(
                job_id=body["job_id"],
                worker_id=worker_id,
                queue=body["queue"],
                token=body["lease_token"],
            ),
            lease_expires_at=datetime.fromisoformat(body["lease_expires_at"]),
        )

    def renew(self, lease: WorkerLease) -> bool:
        response = self._client.post(
            f"/worker/v1/jobs/{lease.job_id}/lease/renew",
            json={"worker_id": lease.worker_id, "lease_token": lease.token},
        )
        if response.status_code == httpx.codes.CONFLICT:
            return False
        self._raise_for_gateway_error(response)
        return True

    def complete(
        self, lease: WorkerLease, *, result_ref: str | None = None
    ) -> JobStatus:
        payload = {"worker_id": lease.worker_id, "lease_token": lease.token}
        if result_ref is not None:
            payload["result_ref"] = result_ref
        response = self._client.post(
            f"/worker/v1/jobs/{lease.job_id}/complete",
            json=payload,
        )
        self._raise_for_terminal_error(response)
        return JobStatus(response.json()["status"])

    def store_result(self, lease: WorkerLease, result: Any) -> str:
        """Serialize a result and upload it through a temporary signed URL."""

        encoded = json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        reservation = self._client.post(
            f"/worker/v1/jobs/{lease.job_id}/result-upload",
            json={"worker_id": lease.worker_id, "lease_token": lease.token},
        )
        self._raise_for_terminal_error(reservation)
        body = reservation.json()
        if body.get("job_id") != lease.job_id:
            raise GatewayRequestError("Gateway returned a result URL for another job")
        upload = self._upload_client.put(
            body["upload_url"],
            content=encoded,
            headers={"Content-Type": "application/json"},
        )
        if not upload.is_success:
            raise GatewayRequestError(
                f"Result upload returned {upload.status_code}: "
                f"{upload.text or 'Unknown storage error'}"
            )
        return str(body["result_ref"])

    def fail(self, lease: WorkerLease, *, error: dict[str, Any]) -> JobStatus:
        response = self._client.post(
            f"/worker/v1/jobs/{lease.job_id}/fail",
            json={
                "worker_id": lease.worker_id,
                "lease_token": lease.token,
                "error": error,
            },
        )
        self._raise_for_terminal_error(response)
        return JobStatus(response.json()["status"])

    @staticmethod
    def _raise_for_terminal_error(response: httpx.Response) -> None:
        if response.status_code == httpx.codes.CONFLICT:
            raise GatewayLeaseRejected(_response_detail(response))
        WorkerGatewayClient._raise_for_gateway_error(response)

    @staticmethod
    def _raise_for_gateway_error(response: httpx.Response) -> None:
        if response.is_success:
            return
        raise GatewayRequestError(
            f"Worker Gateway returned {response.status_code}: "
            f"{_response_detail(response)}"
        )


def _response_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or "Unknown gateway error"
    detail = body.get("detail") if isinstance(body, dict) else None
    return str(detail or body)
