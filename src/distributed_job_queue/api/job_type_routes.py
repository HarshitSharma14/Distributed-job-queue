"""Publisher Job Type catalog routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from distributed_job_queue.api.auth_dependencies import (
    require_publisher_principal,
    require_publisher_write_principal,
)
from distributed_job_queue.api.dependencies import get_handler_storage, get_session
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.api.job_type_schemas import (
    HandlerUploadRequest,
    HandlerUploadResponse,
    HandlerVerificationResponse,
    JobTypeCreateRequest,
    JobTypeResponse,
)
from distributed_job_queue.api.job_type_services import (
    HandlerArtifactNotReady,
    JobTypeConflict,
    JobTypeStateConflict,
    create_draft_job_type,
    disable_visible_job_type,
    get_visible_job_type,
    list_visible_job_types,
    reserve_handler_upload,
    verify_handler_and_activate,
)
from distributed_job_queue.auth.service import AuthenticatedPrincipal
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.persistence.models import HandlerArtifact, JobType
from distributed_job_queue.storage import MinioHandlerStorage

router = APIRouter(prefix="/job-types", tags=["job-types"])


@router.post("", response_model=JobTypeResponse, status_code=status.HTTP_201_CREATED)
def create_job_type(
    request: JobTypeCreateRequest,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_publisher_write_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
) -> JobTypeResponse:
    if UserRole.PUBLISHER not in principal.roles:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="PUBLISHER_ROLE_REQUIRED",
            message="Publisher role required",
        )
    try:
        job_type = create_draft_job_type(
            session,
            publisher_id=principal.user_id,
            name=request.name,
            queue=request.queue,
        )
    except JobTypeConflict as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="JOB_TYPE_CONFLICT",
            message=str(exc),
        ) from exc
    return _response(job_type)


@router.get("", response_model=list[JobTypeResponse])
def list_job_types(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_publisher_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[JobTypeResponse]:
    return [
        _response(job_type)
        for job_type in list_visible_job_types(
            session, principal=principal, limit=limit
        )
    ]


@router.get("/{job_type_id}", response_model=JobTypeResponse)
def get_job_type(
    job_type_id: UUID,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_publisher_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
) -> JobTypeResponse:
    job_type = get_visible_job_type(
        session, str(job_type_id), principal=principal
    )
    if job_type is None:
        raise _not_found()
    return _response(job_type)


@router.post("/{job_type_id}/disable", response_model=JobTypeResponse)
def disable_job_type(
    job_type_id: UUID,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_publisher_write_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
) -> JobTypeResponse:
    job_type = disable_visible_job_type(
        session, str(job_type_id), principal=principal
    )
    if job_type is None:
        raise _not_found()
    return _response(job_type)


@router.post(
    "/{job_type_id}/handler-upload",
    response_model=HandlerUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_handler_upload(
    job_type_id: UUID,
    request: HandlerUploadRequest,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_publisher_write_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[MinioHandlerStorage, Depends(get_handler_storage)],
) -> HandlerUploadResponse:
    try:
        artifact, upload_url = reserve_handler_upload(
            session,
            storage,
            str(job_type_id),
            principal=principal,
            expected_digest=request.expected_sha256,
            expected_size_bytes=request.size_bytes,
        )
    except LookupError as exc:
        raise _not_found() from exc
    except JobTypeStateConflict as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="JOB_TYPE_STATE_CONFLICT",
            message=str(exc),
        ) from exc
    return HandlerUploadResponse(
        artifact_id=artifact.id,
        job_type_id=artifact.job_type_id,
        object_ref=artifact.object_ref,
        upload_url=upload_url,
        expires_at=artifact.upload_expires_at,
    )


@router.post(
    "/{job_type_id}/handler-artifacts/{artifact_id}/verify",
    response_model=HandlerVerificationResponse,
)
def verify_handler_artifact(
    job_type_id: UUID,
    artifact_id: UUID,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_publisher_write_principal)
    ],
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[MinioHandlerStorage, Depends(get_handler_storage)],
) -> HandlerVerificationResponse:
    try:
        artifact, job_type = verify_handler_and_activate(
            session,
            storage,
            str(job_type_id),
            str(artifact_id),
            principal=principal,
        )
    except LookupError as exc:
        raise _not_found() from exc
    except HandlerArtifactNotReady as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="HANDLER_ARTIFACT_NOT_READY",
            message=str(exc),
        ) from exc
    except JobTypeStateConflict as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="JOB_TYPE_STATE_CONFLICT",
            message=str(exc),
        ) from exc
    return _verification_response(artifact, job_type)


def _response(job_type: JobType) -> JobTypeResponse:
    return JobTypeResponse(
        job_type_id=job_type.id,
        publisher_id=job_type.publisher_id,
        name=job_type.name,
        version=job_type.version,
        queue=job_type.queue,
        status=job_type.status,
        handler_ref=job_type.handler_ref,
        handler_digest=job_type.handler_digest,
        created_at=job_type.created_at,
        updated_at=job_type.updated_at,
    )


def _verification_response(
    artifact: HandlerArtifact, job_type: JobType
) -> HandlerVerificationResponse:
    return HandlerVerificationResponse(
        artifact_id=artifact.id,
        artifact_status=artifact.status,
        job_type_status=job_type.status,
        expected_sha256=artifact.expected_digest,
        actual_sha256=artifact.actual_digest,
        expected_size_bytes=artifact.expected_size_bytes,
        actual_size_bytes=artifact.actual_size_bytes,
        rejection_reason=artifact.rejection_reason,
    )


def _not_found() -> APIError:
    return APIError(
        status_code=status.HTTP_404_NOT_FOUND,
        code="JOB_TYPE_NOT_FOUND",
        message="Job Type not found",
    )
