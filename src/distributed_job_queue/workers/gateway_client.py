"""HTTP-only client used by external worker execution agents."""

from __future__ import annotations

import json
import hashlib
from hmac import compare_digest
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


@dataclass(frozen=True, slots=True)
class GatewayRegistration:
    worker_id: str
    job_type_id: str
    capabilities: tuple[str, ...]
    queue: str
    token_expires_at: datetime


@dataclass(frozen=True, slots=True)
class DownloadedHandlerBundle:
    job_type_id: str
    job_type: str
    digest: str
    content: bytes


class HandlerDownloadRejected(GatewayRequestError):
    """Raised when a handler download is oversized, altered, or malformed."""


class WorkerGatewayClient:
    """Expose worker operations without infrastructure credentials."""

    def __init__(
        self,
        api_url: str,
        enrollment_token: str,
        *,
        request_timeout_seconds: float = 10,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_url:
            raise ValueError("api_url must not be empty")
        if not enrollment_token:
            raise ValueError("enrollment_token must not be empty")
        self.request_timeout_seconds = request_timeout_seconds
        self._client = httpx.Client(
            base_url=api_url.rstrip("/"),
            headers={"Authorization": f"Bearer {enrollment_token}"},
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

    def register(self, worker_id: str) -> GatewayRegistration:
        response = self._client.post(
            "/worker/v1/workers/register",
            json={"worker_id": worker_id},
        )
        self._raise_for_gateway_error(response)
        body = response.json()
        worker_token = body.get("worker_token")
        if not isinstance(worker_token, str) or not worker_token:
            raise GatewayRequestError("Gateway did not return a Worker Agent token")
        self._client.headers["Authorization"] = f"Bearer {worker_token}"
        return GatewayRegistration(
            worker_id=str(body["worker_id"]),
            job_type_id=str(body["job_type_id"]),
            capabilities=tuple(body["capabilities"]),
            queue=str(body["queue"]),
            token_expires_at=datetime.fromisoformat(body["token_expires_at"]),
        )

    def heartbeat(self, worker_id: str) -> bool:
        response = self._client.post(
            f"/worker/v1/workers/{worker_id}/heartbeat"
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return False
        self._raise_for_gateway_error(response)
        return True

    def download_handler(self, *, max_bytes: int) -> DownloadedHandlerBundle:
        """Fetch the assigned bundle without exposing object-storage credentials."""

        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        assignment = self._client.get("/worker/v1/handler")
        self._raise_for_gateway_error(assignment)
        body = assignment.json()
        with self._upload_client.stream("GET", body["download_url"]) as response:
            if not response.is_success:
                raise HandlerDownloadRejected(
                    f"Handler download returned {response.status_code}"
                )
            declared_size = response.headers.get("Content-Length")
            if declared_size is not None:
                try:
                    parsed_size = int(declared_size)
                except ValueError as exc:
                    raise HandlerDownloadRejected(
                        "Handler download returned an invalid size"
                    ) from exc
                if parsed_size > max_bytes:
                    raise HandlerDownloadRejected(
                        "Handler bundle exceeds the size limit"
                    )
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise HandlerDownloadRejected(
                        "Handler bundle exceeds the size limit"
                    )
        expected_digest = str(body["sha256"]).lower()
        actual_digest = hashlib.sha256(content).hexdigest()
        if not compare_digest(actual_digest, expected_digest):
            raise HandlerDownloadRejected("Handler bundle digest verification failed")
        return DownloadedHandlerBundle(
            job_type_id=str(body["job_type_id"]),
            job_type=str(body["job_type"]),
            digest=actual_digest,
            content=bytes(content),
        )

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
    if detail is None and isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            detail = error.get("message")
    return str(detail or body)
