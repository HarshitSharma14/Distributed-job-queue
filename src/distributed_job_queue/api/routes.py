"""HTTP routes for job operations."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.api.schemas import (
    JobCreateRequest,
    JobCreateResponse,
    JobDetailResponse,
)
from distributed_job_queue.api.services import (
    IdempotencyConflict,
    get_job_detail,
    submit_job,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    request: JobCreateRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
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
            session, request, idempotency_key=idempotency_key
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if submission.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return submission.response


@router.get("/{job_id}", response_model=JobDetailResponse)
def get_job(
    job_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> JobDetailResponse:
    detail = get_job_detail(session, str(job_id))
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return detail
