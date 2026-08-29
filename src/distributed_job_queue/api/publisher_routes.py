"""Ownership-scoped Publisher dashboard routes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from distributed_job_queue.api.auth_dependencies import (
    require_publisher_dashboard_principal,
)
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.api.publisher_schemas import (
    PublisherAnalyticsResponse,
    PublisherJobListResponse,
)
from distributed_job_queue.api.publisher_services import (
    InvalidDashboardFilter,
    get_publisher_analytics,
    list_publisher_jobs,
)
from distributed_job_queue.auth.service import AuthenticatedPrincipal
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.persistence.repositories.dashboard import PublisherJobFilters

router = APIRouter(prefix="/publisher", tags=["publisher-dashboard"])


@router.get("/jobs", response_model=PublisherJobListResponse)
def publisher_jobs(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_publisher_dashboard_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    job_type_id: UUID | None = None,
    producer_id: UUID | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PublisherJobListResponse:
    try:
        return list_publisher_jobs(
            session,
            publisher_id=principal.user_id,
            filters=_filters(
                status_filter,
                job_type_id,
                producer_id,
                created_after,
                created_before,
            ),
            limit=limit,
            cursor=cursor,
        )
    except InvalidDashboardFilter as exc:
        raise _invalid_filter(exc) from exc


@router.get("/analytics", response_model=PublisherAnalyticsResponse)
def publisher_analytics(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_publisher_dashboard_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    job_type_id: UUID | None = None,
    producer_id: UUID | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> PublisherAnalyticsResponse:
    try:
        return get_publisher_analytics(
            session,
            publisher_id=principal.user_id,
            filters=_filters(
                status_filter,
                job_type_id,
                producer_id,
                created_after,
                created_before,
            ),
        )
    except InvalidDashboardFilter as exc:
        raise _invalid_filter(exc) from exc


def _filters(
    status_filter: JobStatus | None,
    job_type_id: UUID | None,
    producer_id: UUID | None,
    created_after: datetime | None,
    created_before: datetime | None,
) -> PublisherJobFilters:
    return PublisherJobFilters(
        status=status_filter,
        job_type_id=str(job_type_id) if job_type_id else None,
        producer_id=str(producer_id) if producer_id else None,
        created_after=created_after,
        created_before=created_before,
    )


def _invalid_filter(exc: InvalidDashboardFilter) -> APIError:
    return APIError(
        status_code=status.HTTP_400_BAD_REQUEST,
        code="DASHBOARD_FILTER_INVALID",
        message=str(exc),
    )
