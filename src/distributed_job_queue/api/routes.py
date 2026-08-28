"""HTTP routes for job operations."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.orm import Session

from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.api.auth_dependencies import (
    require_job_read_principal,
    require_job_submission_principal,
)
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.api.schemas import (
    JobCreateRequest,
    JobCreateResponse,
    JobDetailResponse,
)
from distributed_job_queue.api.services import (
    IdempotencyConflict,
    JobTypeUnavailable,
    get_job_detail,
    submit_job,
)
from distributed_job_queue.auth.service import AuthenticatedPrincipal
from distributed_job_queue.common.metrics import JOBS_SUBMITTED

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    request: JobCreateRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_job_submission_principal)
    ],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
) -> JobCreateResponse:
    try:
        submission = submit_job(
            session,
            request,
            producer_id=principal.user_id,
            idempotency_key=idempotency_key,
        )
    except IdempotencyConflict as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="IDEMPOTENCY_CONFLICT",
            message=str(exc),
        ) from exc
    except JobTypeUnavailable as exc:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="JOB_TYPE_NOT_FOUND",
            message=str(exc),
        ) from exc
    if submission.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    else:
        JOBS_SUBMITTED.labels(queue=submission.response.queue).inc()
    logger.info(
        "Job submission accepted",
        extra={
            "event": "job.submitted",
            "job_id": submission.response.job_id,
            "job_type": submission.response.type,
            "queue": submission.response.queue,
            "priority": submission.response.priority,
            "replayed": submission.replayed,
        },
    )
    return submission.response


@router.get("/{job_id}", response_model=JobDetailResponse)
def get_job(
    job_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_job_read_principal)
    ],
) -> JobDetailResponse:
    detail = get_job_detail(session, str(job_id), principal=principal)
    if detail is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="JOB_NOT_FOUND",
            message="Job not found",
        )
    return detail
