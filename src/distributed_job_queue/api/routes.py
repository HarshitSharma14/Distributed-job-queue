"""HTTP routes for job operations."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.api.schemas import (
    JobCreateRequest,
    JobCreateResponse,
    JobDetailResponse,
)
from distributed_job_queue.api.services import get_job_detail, submit_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    request: JobCreateRequest,
    session: Annotated[Session, Depends(get_session)],
) -> JobCreateResponse:
    return submit_job(session, request)


@router.get("/{job_id}", response_model=JobDetailResponse)
def get_job(
    job_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> JobDetailResponse:
    detail = get_job_detail(session, str(job_id))
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return detail
