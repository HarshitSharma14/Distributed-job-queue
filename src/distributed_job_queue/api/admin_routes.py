"""Global, read-only Admin control-plane routes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from distributed_job_queue.api.admin_schemas import (
    AdminDeadLetterListResponse,
    AdminOverviewResponse,
    AdminQueueListResponse,
    AdminWorkerListResponse,
)
from distributed_job_queue.api.admin_services import (
    InvalidAdminDashboardFilter,
    get_admin_overview,
    get_admin_queues,
    list_admin_workers,
)
from distributed_job_queue.api.auth_dependencies import require_admin_principal
from distributed_job_queue.api.dashboard_schemas import (
    DashboardAnalyticsResponse,
    DashboardJobListResponse,
)
from distributed_job_queue.api.dashboard_services import (
    InvalidDashboardFilter,
    get_dashboard_analytics,
    list_dashboard_jobs,
)
from distributed_job_queue.api.dependencies import (
    get_prometheus_client,
    get_redis_queue,
    get_session,
)
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.api.schemas import NAME_PATTERN
from distributed_job_queue.auth.service import AuthenticatedPrincipal
from distributed_job_queue.common.prometheus import PrometheusQueryClient
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.domain.worker import WorkerStatus
from distributed_job_queue.persistence.repositories.admin_dashboard import (
    AdminWorkerFilters,
)
from distributed_job_queue.persistence.repositories.dashboard import DashboardJobFilters
from distributed_job_queue.queueing import RedisQueue

router = APIRouter(prefix="/admin", tags=["admin-dashboard"])


@router.get("/overview", response_model=AdminOverviewResponse)
def admin_overview(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin_principal)],
    session: Annotated[Session, Depends(get_session)],
    prometheus: Annotated[
        PrometheusQueryClient | None, Depends(get_prometheus_client)
    ],
    window: Literal["1h", "6h", "24h", "7d"] = "24h",
) -> AdminOverviewResponse:
    return get_admin_overview(
        session,
        prometheus,
        admin_id=principal.user_id,
        window=window,
    )


@router.get("/jobs", response_model=DashboardJobListResponse)
def admin_jobs(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin_principal)],
    session: Annotated[Session, Depends(get_session)],
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    job_type_id: UUID | None = None,
    publisher_id: UUID | None = None,
    producer_id: UUID | None = None,
    queue: Annotated[
        str | None, Query(min_length=1, max_length=100, pattern=NAME_PATTERN)
    ] = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DashboardJobListResponse:
    try:
        return list_dashboard_jobs(
            session,
            owner="admin",
            owner_id=principal.user_id,
            filters=_job_filters(
                status_filter,
                job_type_id,
                publisher_id,
                producer_id,
                queue,
                created_after,
                created_before,
            ),
            limit=limit,
            cursor=cursor,
        )
    except InvalidDashboardFilter as exc:
        raise _invalid_filter(exc) from exc


@router.get("/analytics", response_model=DashboardAnalyticsResponse)
def admin_analytics(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin_principal)],
    session: Annotated[Session, Depends(get_session)],
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    job_type_id: UUID | None = None,
    publisher_id: UUID | None = None,
    producer_id: UUID | None = None,
    queue: Annotated[
        str | None, Query(min_length=1, max_length=100, pattern=NAME_PATTERN)
    ] = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> DashboardAnalyticsResponse:
    try:
        return get_dashboard_analytics(
            session,
            owner="admin",
            owner_id=principal.user_id,
            filters=_job_filters(
                status_filter,
                job_type_id,
                publisher_id,
                producer_id,
                queue,
                created_after,
                created_before,
            ),
        )
    except InvalidDashboardFilter as exc:
        raise _invalid_filter(exc) from exc


@router.get("/dead-letters", response_model=AdminDeadLetterListResponse)
def admin_dead_letters(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin_principal)],
    session: Annotated[Session, Depends(get_session)],
    job_type_id: UUID | None = None,
    publisher_id: UUID | None = None,
    producer_id: UUID | None = None,
    queue: Annotated[
        str | None, Query(min_length=1, max_length=100, pattern=NAME_PATTERN)
    ] = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminDeadLetterListResponse:
    try:
        result = list_dashboard_jobs(
            session,
            owner="admin",
            owner_id=principal.user_id,
            filters=_job_filters(
                JobStatus.DEAD_LETTERED,
                job_type_id,
                publisher_id,
                producer_id,
                queue,
                created_after,
                created_before,
            ),
            limit=limit,
            cursor=cursor,
        )
    except InvalidDashboardFilter as exc:
        raise _invalid_filter(exc) from exc
    return AdminDeadLetterListResponse(
        items=result.items,
        next_cursor=result.next_cursor,
    )


@router.get("/workers", response_model=AdminWorkerListResponse)
def admin_workers(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin_principal)],
    session: Annotated[Session, Depends(get_session)],
    status_filter: Annotated[WorkerStatus | None, Query(alias="status")] = None,
    owner_user_id: UUID | None = None,
    capability: Annotated[
        str | None, Query(min_length=1, max_length=100, pattern=NAME_PATTERN)
    ] = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminWorkerListResponse:
    try:
        return list_admin_workers(
            session,
            filters=AdminWorkerFilters(
                status=status_filter,
                owner_user_id=str(owner_user_id) if owner_user_id else None,
                capability=capability,
            ),
            limit=limit,
            cursor=cursor,
        )
    except InvalidAdminDashboardFilter as exc:
        raise _invalid_filter(exc) from exc


@router.get("/queues", response_model=AdminQueueListResponse)
def admin_queues(
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_admin_principal)],
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[RedisQueue, Depends(get_redis_queue)],
) -> AdminQueueListResponse:
    return get_admin_queues(session, queue)


def _job_filters(
    status_filter: JobStatus | None,
    job_type_id: UUID | None,
    publisher_id: UUID | None,
    producer_id: UUID | None,
    queue: str | None,
    created_after: datetime | None,
    created_before: datetime | None,
) -> DashboardJobFilters:
    return DashboardJobFilters(
        status=status_filter,
        job_type_id=str(job_type_id) if job_type_id else None,
        publisher_id=str(publisher_id) if publisher_id else None,
        producer_id=str(producer_id) if producer_id else None,
        queue=queue,
        created_after=created_after,
        created_before=created_before,
    )


def _invalid_filter(exc: ValueError) -> APIError:
    return APIError(
        status_code=status.HTTP_400_BAD_REQUEST,
        code="ADMIN_DASHBOARD_FILTER_INVALID",
        message=str(exc),
    )
