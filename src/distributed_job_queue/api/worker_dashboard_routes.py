"""Human-facing Worker assignment and attempt-history routes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from distributed_job_queue.api.auth_dependencies import (
    require_worker_dashboard_principal,
)
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.api.schemas import NAME_PATTERN
from distributed_job_queue.api.worker_dashboard_schemas import (
    WorkerAssignmentListResponse,
    WorkerAttemptListResponse,
)
from distributed_job_queue.api.worker_dashboard_services import (
    InvalidWorkerDashboardFilter,
    list_worker_assignments,
    list_worker_attempts,
)
from distributed_job_queue.auth.service import AuthenticatedPrincipal
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.repositories.worker_dashboard import (
    WorkerAssignmentFilters,
    WorkerAttemptFilters,
)

router = APIRouter(prefix="/worker-management", tags=["worker-dashboard"])


@router.get("/assignments", response_model=WorkerAssignmentListResponse)
def worker_assignments(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_worker_dashboard_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
    worker_id: Annotated[
        str | None, Query(min_length=1, max_length=100, pattern=NAME_PATTERN)
    ] = None,
    job_type_id: UUID | None = None,
    queue: Annotated[
        str | None, Query(min_length=1, max_length=100, pattern=NAME_PATTERN)
    ] = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> WorkerAssignmentListResponse:
    try:
        return list_worker_assignments(
            session,
            owner_user_id=principal.user_id,
            filters=WorkerAssignmentFilters(
                worker_id=worker_id,
                job_type_id=str(job_type_id) if job_type_id else None,
                queue=queue,
            ),
            limit=limit,
            cursor=cursor,
        )
    except InvalidWorkerDashboardFilter as exc:
        raise _invalid_filter(exc) from exc


@router.get("/attempts", response_model=WorkerAttemptListResponse)
def worker_attempts(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_worker_dashboard_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
    worker_id: Annotated[
        str | None, Query(min_length=1, max_length=100, pattern=NAME_PATTERN)
    ] = None,
    job_type_id: UUID | None = None,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> WorkerAttemptListResponse:
    try:
        return list_worker_attempts(
            session,
            owner_user_id=principal.user_id,
            filters=WorkerAttemptFilters(
                worker_id=worker_id,
                job_type_id=str(job_type_id) if job_type_id else None,
                status=status_filter,
                started_after=started_after,
                started_before=started_before,
            ),
            limit=limit,
            cursor=cursor,
        )
    except InvalidWorkerDashboardFilter as exc:
        raise _invalid_filter(exc) from exc


def _invalid_filter(exc: InvalidWorkerDashboardFilter) -> APIError:
    return APIError(
        status_code=status.HTTP_400_BAD_REQUEST,
        code="WORKER_DASHBOARD_FILTER_INVALID",
        message=str(exc),
    )
