"""Ownership-scoped Producer dashboard routes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from distributed_job_queue.api.auth_dependencies import (
    require_producer_dashboard_principal,
)
from distributed_job_queue.api.dashboard_schemas import (
    DashboardAnalyticsResponse,
    DashboardJobListResponse,
)
from distributed_job_queue.api.dashboard_services import (
    InvalidDashboardFilter,
    get_dashboard_analytics,
    list_dashboard_jobs,
)
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.auth.service import AuthenticatedPrincipal
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.repositories.dashboard import DashboardJobFilters

router = APIRouter(prefix="/producer", tags=["producer-dashboard"])


@router.get("/jobs", response_model=DashboardJobListResponse)
def producer_jobs(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_producer_dashboard_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    job_type_id: UUID | None = None,
    publisher_id: UUID | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DashboardJobListResponse:
    try:
        return list_dashboard_jobs(
            session,
            owner="producer",
            owner_id=principal.user_id,
            filters=_filters(
                status_filter,
                job_type_id,
                publisher_id,
                created_after,
                created_before,
            ),
            limit=limit,
            cursor=cursor,
        )
    except InvalidDashboardFilter as exc:
        raise _invalid_filter(exc) from exc


@router.get("/analytics", response_model=DashboardAnalyticsResponse)
def producer_analytics(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_producer_dashboard_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    job_type_id: UUID | None = None,
    publisher_id: UUID | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> DashboardAnalyticsResponse:
    try:
        return get_dashboard_analytics(
            session,
            owner="producer",
            owner_id=principal.user_id,
            filters=_filters(
                status_filter,
                job_type_id,
                publisher_id,
                created_after,
                created_before,
            ),
        )
    except InvalidDashboardFilter as exc:
        raise _invalid_filter(exc) from exc


def _filters(
    status_filter: JobStatus | None,
    job_type_id: UUID | None,
    publisher_id: UUID | None,
    created_after: datetime | None,
    created_before: datetime | None,
) -> DashboardJobFilters:
    return DashboardJobFilters(
        status=status_filter,
        job_type_id=str(job_type_id) if job_type_id else None,
        publisher_id=str(publisher_id) if publisher_id else None,
        created_after=created_after,
        created_before=created_before,
    )


def _invalid_filter(exc: InvalidDashboardFilter) -> APIError:
    return APIError(
        status_code=status.HTTP_400_BAD_REQUEST,
        code="DASHBOARD_FILTER_INVALID",
        message=str(exc),
    )
