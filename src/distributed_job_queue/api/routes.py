"""HTTP routes for job operations."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.api.schemas import JobCreateRequest, JobCreateResponse
from distributed_job_queue.api.services import submit_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    request: JobCreateRequest,
    session: Annotated[Session, Depends(get_session)],
) -> JobCreateResponse:
    return submit_job(session, request)
