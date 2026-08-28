"""Application operations exposed only through the Worker Gateway."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from distributed_job_queue.api.schemas import (
    WorkerClaimRequest,
    WorkerClaimResponse,
    WorkerHeartbeatResponse,
    WorkerLeaseRenewRequest,
    WorkerLeaseRenewResponse,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
)
from distributed_job_queue.common.config import load_settings
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.domain.worker import WorkerStatus
from distributed_job_queue.persistence.repositories import (
    ConcurrentJobUpdate,
    JobRepository,
    WorkerRepository,
)
from distributed_job_queue.queueing import JobLease, RedisQueue


class WorkerUnavailable(LookupError):
    """Raised when a worker is unknown or not currently online."""


class WorkerCapabilityMismatch(ValueError):
    """Raised when a worker claims work it cannot execute."""


class WorkerLeaseLost(RuntimeError):
    """Raised when a worker cannot prove current ownership of a job."""


def register_gateway_worker(
    session: Session, request: WorkerRegistrationRequest
) -> WorkerRegistrationResponse:
    """Register or reconnect one worker through the platform boundary."""

    now = datetime.now(timezone.utc)
    worker = WorkerRepository(session).register(
        request.worker_id,
        capabilities=request.capabilities,
        now=now,
    )
    return WorkerRegistrationResponse(
        worker_id=worker.id,
        capabilities=worker.capabilities,
        status=WorkerStatus(worker.status),
        registered_at=worker.registered_at,
        last_heartbeat_at=worker.last_heartbeat_at,
        heartbeat_interval_seconds=(
            load_settings().worker_heartbeat_interval_seconds
        ),
    )


def heartbeat_gateway_worker(
    session: Session, worker_id: str
) -> WorkerHeartbeatResponse | None:
    """Record liveness for a registered worker."""

    now = datetime.now(timezone.utc)
    if not WorkerRepository(session).heartbeat(worker_id, now=now):
        return None
    return WorkerHeartbeatResponse(
        worker_id=worker_id,
        status=WorkerStatus.ONLINE,
        last_heartbeat_at=now,
    )


def claim_gateway_job(
    queue: RedisQueue,
    request: WorkerClaimRequest,
    *,
    session_factory,
) -> WorkerClaimResponse | None:
    """Long-poll and durably hand one compatible job to a worker."""

    settings = load_settings()
    wait_seconds = (
        settings.worker_long_poll_seconds
        if request.wait_seconds is None
        else request.wait_seconds
    )

    with session_factory() as session:
        worker = WorkerRepository(session).get(request.worker_id)
        if worker is None:
            raise WorkerUnavailable(f"Worker {request.worker_id} is not registered")
        if worker.status != WorkerStatus.ONLINE.value:
            raise WorkerUnavailable(f"Worker {request.worker_id} is not online")
        capabilities = set(worker.capabilities)

    lease = queue.long_poll(
        request.queue,
        worker_id=request.worker_id,
        lease_seconds=settings.job_lease_seconds,
        wait_seconds=wait_seconds,
    )
    if lease is None:
        return None

    try:
        with session_factory.begin() as session:
            repository = JobRepository(session)
            job = repository.get(lease.job_id)
            if job is None or job.status != JobStatus.QUEUED.value:
                _release_stale_gateway_claim(queue, lease)
                return None
            if job.type not in capabilities:
                raise WorkerCapabilityMismatch(
                    f"Worker {request.worker_id} does not support {job.type}"
                )

            lease_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=settings.job_lease_seconds
            )
            running = repository.mark_running(
                job.id,
                worker_id=request.worker_id,
                lease_token=lease.token,
                lease_expires_at=lease_expires_at,
            )
            return WorkerClaimResponse(
                job_id=running.id,
                attempt_number=running.attempts,
                type=running.type,
                queue=running.queue,
                payload=dict(running.payload),
                lease_token=lease.token,
                lease_expires_at=lease_expires_at,
            )
    except ConcurrentJobUpdate:
        _release_stale_gateway_claim(queue, lease)
        return None
    except Exception:
        queue.abandon_claim(
            lease.job_id,
            queue=lease.queue,
            worker_id=lease.worker_id,
            token=lease.token,
        )
        raise


def renew_gateway_lease(
    queue: RedisQueue,
    job_id: str,
    request: WorkerLeaseRenewRequest,
    *,
    session_factory,
) -> WorkerLeaseRenewResponse:
    """Renew a live fenced lease without exposing either backing store."""

    settings = load_settings()
    now = datetime.now(timezone.utc)
    lease_expires_at = now + timedelta(seconds=settings.job_lease_seconds)
    lease_token = str(request.lease_token)

    with session_factory.begin() as session:
        repository = JobRepository(session)
        job = repository.get(job_id)
        if job is None:
            raise WorkerLeaseLost(f"Worker no longer owns job {job_id}")
        queue_name = job.queue
        renewed = repository.renew_lease(
            job_id,
            worker_id=request.worker_id,
            lease_token=lease_token,
            now=now,
            lease_expires_at=lease_expires_at,
        )
        if not renewed:
            raise WorkerLeaseLost(f"Worker no longer owns job {job_id}")

    renewed_in_redis = queue.renew_lease(
        job_id,
        queue=queue_name,
        worker_id=request.worker_id,
        token=lease_token,
        lease_seconds=settings.job_lease_seconds,
    )
    if not renewed_in_redis:
        raise WorkerLeaseLost(f"Worker no longer owns job {job_id}")

    return WorkerLeaseRenewResponse(
        job_id=job_id,
        worker_id=request.worker_id,
        lease_expires_at=lease_expires_at,
    )


def _release_stale_gateway_claim(queue: RedisQueue, lease: JobLease) -> None:
    queue.release_lease(
        lease.job_id,
        queue=lease.queue,
        worker_id=lease.worker_id,
        token=lease.token,
    )
