"""Worker-facing gateway routes with no infrastructure exposure."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session, sessionmaker

from distributed_job_queue.api.dependencies import (
    get_session,
    get_redis_queue,
    get_session_factory,
    require_worker_token,
)
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
)
from distributed_job_queue.api.worker_gateway_services import (
    WorkerCapabilityMismatch,
    WorkerLeaseLost,
    WorkerUnavailable,
    claim_gateway_job,
    complete_gateway_job,
    fail_gateway_job,
    heartbeat_gateway_worker,
    register_gateway_worker,
    renew_gateway_lease,
)
from distributed_job_queue.queueing import RedisQueue

router = APIRouter(
    prefix="/worker/v1",
    tags=["worker-gateway"],
    dependencies=[Depends(require_worker_token)],
)


@router.post(
    "/workers/register",
    response_model=WorkerRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_worker(
    request: WorkerRegistrationRequest,
    session: Annotated[Session, Depends(get_session)],
) -> WorkerRegistrationResponse:
    return register_gateway_worker(session, request)


@router.post(
    "/workers/{worker_id}/heartbeat",
    response_model=WorkerHeartbeatResponse,
)
def heartbeat_worker(
    worker_id: Annotated[
        str,
        Path(min_length=1, max_length=100, pattern=NAME_PATTERN),
    ],
    session: Annotated[Session, Depends(get_session)],
) -> WorkerHeartbeatResponse:
    heartbeat = heartbeat_gateway_worker(session, worker_id)
    if heartbeat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Worker not found",
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
    queue: Annotated[RedisQueue, Depends(get_redis_queue)],
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> WorkerClaimResponse | Response:
    try:
        claim = claim_gateway_job(
            queue,
            request,
            session_factory=session_factory,
        )
    except WorkerUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except WorkerCapabilityMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
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
    queue: Annotated[RedisQueue, Depends(get_redis_queue)],
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> WorkerLeaseRenewResponse:
    try:
        return renew_gateway_lease(
            queue,
            str(job_id),
            request,
            session_factory=session_factory,
        )
    except WorkerLeaseLost as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
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
    queue: Annotated[RedisQueue, Depends(get_redis_queue)],
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> WorkerFinalizationResponse:
    try:
        return complete_gateway_job(
            queue,
            str(job_id),
            request,
            session_factory=session_factory,
        )
    except WorkerLeaseLost as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
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
    queue: Annotated[RedisQueue, Depends(get_redis_queue)],
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> WorkerFinalizationResponse:
    try:
        return fail_gateway_job(
            queue,
            str(job_id),
            request,
            session_factory=session_factory,
        )
    except WorkerLeaseLost as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
