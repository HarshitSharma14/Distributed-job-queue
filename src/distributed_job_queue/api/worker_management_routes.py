"""Human-facing Worker Agent enrollment and credential management."""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from distributed_job_queue.api.auth_dependencies import require_csrf, require_current_principal
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.api.worker_management_schemas import (
    WorkerAgentResponse,
    WorkerEnrollmentCreateRequest,
    WorkerEnrollmentCreatedResponse,
)
from distributed_job_queue.auth.service import AuthenticatedPrincipal
from distributed_job_queue.auth.worker_credentials import (
    WorkerEnrollmentRejected,
    issue_worker_enrollment,
)
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.persistence.models import Worker, WorkerCredential

router = APIRouter(prefix="/worker-management", tags=["worker-management"])


@router.post(
    "/enrollments",
    response_model=WorkerEnrollmentCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_enrollment(
    request: WorkerEnrollmentCreateRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_csrf)],
    session: Annotated[Session, Depends(get_session)],
) -> WorkerEnrollmentCreatedResponse:
    _require_worker_role(principal)
    try:
        result = issue_worker_enrollment(
            session,
            owner_user_id=principal.user_id,
            job_type_id=str(request.job_type_id),
            lifetime_minutes=request.expires_in_minutes,
        )
    except WorkerEnrollmentRejected as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="WORKER_ENROLLMENT_REJECTED",
            message=str(exc),
        ) from exc
    enrollment = result.enrollment
    return WorkerEnrollmentCreatedResponse(
        enrollment_id=enrollment.id,
        job_type_id=enrollment.job_type_id,
        token=result.raw_token,
        token_prefix=enrollment.token_prefix,
        created_at=enrollment.created_at,
        expires_at=enrollment.expires_at,
    )


@router.get("/agents", response_model=list[WorkerAgentResponse])
def list_agents(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_current_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
) -> list[WorkerAgentResponse]:
    _require_worker_role(principal)
    workers = list(
        session.scalars(
            select(Worker)
            .where(Worker.owner_user_id == principal.user_id)
            .order_by(Worker.registered_at.desc())
        )
    )
    return [_agent_response(session, worker) for worker in workers]


@router.delete(
    "/agents/{worker_id}/credential",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_agent_credential(
    worker_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_csrf)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    _require_worker_role(principal)
    worker = session.scalar(
        select(Worker).where(
            Worker.id == worker_id,
            Worker.owner_user_id == principal.user_id,
        )
    )
    if worker is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="WORKER_AGENT_NOT_FOUND",
            message="Worker Agent not found",
        )
    current_time = datetime.now(timezone.utc)
    credentials = list(
        session.scalars(
            select(WorkerCredential).where(
                WorkerCredential.worker_id == worker.id,
                WorkerCredential.revoked_at.is_(None),
            )
        )
    )
    for credential in credentials:
        credential.revoked_at = current_time
    session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _agent_response(session: Session, worker: Worker) -> WorkerAgentResponse:
    credential = session.scalar(
        select(WorkerCredential)
        .where(WorkerCredential.worker_id == worker.id)
        .order_by(WorkerCredential.created_at.desc())
        .limit(1)
    )
    return WorkerAgentResponse(
        worker_id=worker.id,
        capabilities=worker.capabilities,
        status=worker.status,
        registered_at=worker.registered_at,
        last_heartbeat_at=worker.last_heartbeat_at,
        credential_id=credential.id if credential else None,
        credential_prefix=credential.token_prefix if credential else None,
        credential_expires_at=credential.expires_at if credential else None,
        credential_revoked_at=credential.revoked_at if credential else None,
    )


def _require_worker_role(principal: AuthenticatedPrincipal) -> None:
    if UserRole.WORKER not in principal.roles:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="WORKER_ROLE_REQUIRED",
            message="Worker role required",
        )
