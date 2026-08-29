"""Worker-facing gateway routes with no infrastructure exposure."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.orm import Session, sessionmaker

from distributed_job_queue.api.dependencies import (
    get_session,
    get_redis_queue,
    get_result_storage,
    get_session_factory,
    require_worker_agent,
    require_worker_enrollment,
)
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.api.schemas import (
    NAME_PATTERN,
    WorkerClaimRequest,
    WorkerClaimResponse,
    WorkerCompletionRequest,
    WorkerFailureRequest,
    WorkerFinalizationResponse,
    WorkerHeartbeatResponse,
    WorkerLeaseRenewRequest,
    WorkerLeaseRenewResponse,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
    WorkerResultUploadRequest,
    WorkerResultUploadResponse,
)
from distributed_job_queue.api.worker_gateway_services import (
    WorkerCapabilityMismatch,
    WorkerLeaseLost,
    WorkerResultRejected,
    WorkerUnavailable,
    claim_gateway_job,
    complete_gateway_job,
    create_gateway_result_upload,
    fail_gateway_job,
    heartbeat_gateway_worker,
    register_gateway_worker,
    renew_gateway_lease,
)
from distributed_job_queue.queueing import RedisQueue
from distributed_job_queue.storage import MinioResultStorage
from distributed_job_queue.common.metrics import LEASE_LOSSES
from distributed_job_queue.auth.worker_credentials import (
    WorkerAgentPrincipal,
    WorkerEnrollmentPrincipal,
    WorkerRegistrationRejected,
)
from distributed_job_queue.domain.identity import JobTypeStatus

router = APIRouter(
    prefix="/worker/v1",
    tags=["worker-gateway"],
)


@router.post(
    "/workers/register",
    response_model=WorkerRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_worker(
    request: WorkerRegistrationRequest,
    principal: Annotated[
        WorkerEnrollmentPrincipal, Depends(require_worker_enrollment)
    ],
    session: Annotated[Session, Depends(get_session)],
) -> WorkerRegistrationResponse:
    try:
        return register_gateway_worker(session, request, principal=principal)
    except WorkerRegistrationRejected as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="WORKER_REGISTRATION_REJECTED",
            message=str(exc),
        ) from exc


@router.post(
    "/workers/{worker_id}/heartbeat",
    response_model=WorkerHeartbeatResponse,
)
def heartbeat_worker(
    worker_id: Annotated[
        str,
        Path(min_length=1, max_length=100, pattern=NAME_PATTERN),
    ],
    principal: Annotated[WorkerAgentPrincipal, Depends(require_worker_agent)],
    session: Annotated[Session, Depends(get_session)],
) -> WorkerHeartbeatResponse:
    _require_bound_worker(principal, worker_id)
    heartbeat = heartbeat_gateway_worker(session, worker_id)
    if heartbeat is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="WORKER_NOT_FOUND",
            message="Worker not found",
        )
    return heartbeat


@router.post(
    "/jobs/claim",
    response_model=WorkerClaimResponse,
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "No compatible job available"},
        status.HTTP_409_CONFLICT: {"description": "Worker cannot claim this job"},
    },
)
def claim_job(
    request: WorkerClaimRequest,
    principal: Annotated[WorkerAgentPrincipal, Depends(require_worker_agent)],
    queue: Annotated[RedisQueue, Depends(get_redis_queue)],
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> WorkerClaimResponse | Response:
    _require_bound_worker(principal, request.worker_id)
    if principal.job_type_status != JobTypeStatus.ACTIVE.value:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="JOB_TYPE_NOT_ACTIVE",
            message="Assigned Job Type is not active",
        )
    if request.queue != principal.queue:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="WORKER_QUEUE_MISMATCH",
            message="Worker Agent token is not valid for this queue",
        )
    try:
        claim = claim_gateway_job(
            queue,
            request,
            session_factory=session_factory,
            authorized_job_type_id=principal.job_type_id,
        )
    except WorkerUnavailable as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="WORKER_UNAVAILABLE",
            message=str(exc),
        ) from exc
    except WorkerCapabilityMismatch as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="WORKER_CAPABILITY_MISMATCH",
            message=str(exc),
        ) from exc
    if claim is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return claim


@router.post(
    "/jobs/{job_id}/lease/renew",
    response_model=WorkerLeaseRenewResponse,
    responses={
        status.HTTP_409_CONFLICT: {"description": "Worker no longer owns the job"}
    },
)
def renew_job_lease(
    job_id: UUID,
    request: WorkerLeaseRenewRequest,
    principal: Annotated[WorkerAgentPrincipal, Depends(require_worker_agent)],
    queue: Annotated[RedisQueue, Depends(get_redis_queue)],
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> WorkerLeaseRenewResponse:
    _require_bound_worker(principal, request.worker_id)
    try:
        return renew_gateway_lease(
            queue,
            str(job_id),
            request,
            session_factory=session_factory,
        )
    except WorkerLeaseLost as exc:
        LEASE_LOSSES.labels(operation="renew").inc()
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="WORKER_LEASE_LOST",
            message=str(exc),
        ) from exc


@router.post(
    "/jobs/{job_id}/result-upload",
    response_model=WorkerResultUploadResponse,
    responses={
        status.HTTP_409_CONFLICT: {"description": "Worker no longer owns the job"}
    },
)
def create_result_upload(
    job_id: UUID,
    request: WorkerResultUploadRequest,
    principal: Annotated[WorkerAgentPrincipal, Depends(require_worker_agent)],
    storage: Annotated[MinioResultStorage, Depends(get_result_storage)],
    session: Annotated[Session, Depends(get_session)],
) -> WorkerResultUploadResponse:
    _require_bound_worker(principal, request.worker_id)
    try:
        return create_gateway_result_upload(
            session,
            storage,
            str(job_id),
            request,
        )
    except WorkerLeaseLost as exc:
        LEASE_LOSSES.labels(operation="result_upload").inc()
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="WORKER_LEASE_LOST",
            message=str(exc),
        ) from exc


@router.post(
    "/jobs/{job_id}/complete",
    response_model=WorkerFinalizationResponse,
    responses={
        status.HTTP_409_CONFLICT: {"description": "Worker no longer owns the job"}
    },
)
def complete_job(
    job_id: UUID,
    request: WorkerCompletionRequest,
    principal: Annotated[WorkerAgentPrincipal, Depends(require_worker_agent)],
    queue: Annotated[RedisQueue, Depends(get_redis_queue)],
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> WorkerFinalizationResponse:
    _require_bound_worker(principal, request.worker_id)
    try:
        return complete_gateway_job(
            queue,
            str(job_id),
            request,
            session_factory=session_factory,
        )
    except WorkerLeaseLost as exc:
        LEASE_LOSSES.labels(operation="complete").inc()
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="WORKER_LEASE_LOST",
            message=str(exc),
        ) from exc
    except WorkerResultRejected as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="RESULT_REFERENCE_REJECTED",
            message=str(exc),
        ) from exc


@router.post(
    "/jobs/{job_id}/fail",
    response_model=WorkerFinalizationResponse,
    responses={
        status.HTTP_409_CONFLICT: {"description": "Worker no longer owns the job"}
    },
)
def fail_job(
    job_id: UUID,
    request: WorkerFailureRequest,
    principal: Annotated[WorkerAgentPrincipal, Depends(require_worker_agent)],
    queue: Annotated[RedisQueue, Depends(get_redis_queue)],
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> WorkerFinalizationResponse:
    _require_bound_worker(principal, request.worker_id)
    try:
        return fail_gateway_job(
            queue,
            str(job_id),
            request,
            session_factory=session_factory,
        )
    except WorkerLeaseLost as exc:
        LEASE_LOSSES.labels(operation="fail").inc()
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="WORKER_LEASE_LOST",
            message=str(exc),
        ) from exc


def _require_bound_worker(
    principal: WorkerAgentPrincipal, requested_worker_id: str
) -> None:
    if principal.worker_id != requested_worker_id:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="WORKER_IDENTITY_MISMATCH",
            message="Worker Agent token is not valid for this worker ID",
        )
