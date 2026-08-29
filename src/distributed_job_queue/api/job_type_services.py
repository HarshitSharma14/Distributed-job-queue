"""Publisher-owned Job Type catalog operations."""

from datetime import datetime, timezone
from uuid import uuid4

from minio.error import S3Error
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from distributed_job_queue.auth.service import AuthenticatedPrincipal
from distributed_job_queue.auth.handler_signing import HandlerSigningError, sign_release
from distributed_job_queue.common.config import load_settings
from distributed_job_queue.domain.identity import (
    HandlerArtifactStatus,
    JobTypeStatus,
    UserRole,
)
from distributed_job_queue.persistence.models import HandlerArtifact, JobType
from distributed_job_queue.persistence.repositories import IdentityRepository
from distributed_job_queue.storage import MinioHandlerStorage


class JobTypeConflict(ValueError):
    """Raised when the same Publisher already owns the requested version."""


class JobTypeStateConflict(ValueError):
    """Raised when an operation is invalid for the Job Type lifecycle state."""


class HandlerArtifactNotReady(ValueError):
    """Raised when the reserved handler object is not available for verification."""


class HandlerApprovalConflict(ValueError):
    """Raised when an Admin decision is invalid for the release state."""


class HandlerSigningUnavailable(RuntimeError):
    """Raised when the platform cannot sign an approved release."""


def create_draft_job_type(
    session: Session,
    *,
    publisher_id: str,
    name: str,
    queue: str,
) -> JobType:
    try:
        with session.begin_nested():
            return IdentityRepository(session).create_job_type(
                publisher_id=publisher_id,
                name=name,
                version=1,
                queue=queue,
                status=JobTypeStatus.DRAFT,
            )
    except IntegrityError as exc:
        raise JobTypeConflict("Job Type version already exists") from exc


def list_visible_job_types(
    session: Session,
    *,
    principal: AuthenticatedPrincipal,
    limit: int,
) -> list[JobType]:
    publisher_id = None if UserRole.ADMIN in principal.roles else principal.user_id
    return IdentityRepository(session).list_job_types(
        publisher_id=publisher_id, limit=limit
    )


def get_visible_job_type(
    session: Session,
    job_type_id: str,
    *,
    principal: AuthenticatedPrincipal,
    for_update: bool = False,
) -> JobType | None:
    repository = IdentityRepository(session)
    if UserRole.ADMIN in principal.roles:
        return repository.get_job_type(job_type_id, for_update=for_update)
    return repository.get_owned_job_type(
        job_type_id,
        publisher_id=principal.user_id,
        for_update=for_update,
    )


def disable_visible_job_type(
    session: Session,
    job_type_id: str,
    *,
    principal: AuthenticatedPrincipal,
) -> JobType | None:
    job_type = get_visible_job_type(session, job_type_id, principal=principal)
    if job_type is None:
        return None
    return IdentityRepository(session).disable_job_type(job_type)


def reserve_handler_upload(
    session: Session,
    storage: MinioHandlerStorage,
    job_type_id: str,
    *,
    principal: AuthenticatedPrincipal,
    expected_digest: str,
    expected_size_bytes: int,
) -> tuple[HandlerArtifact, str]:
    settings = load_settings()
    if expected_size_bytes > settings.handler_max_bytes:
        raise JobTypeStateConflict("Handler artifact exceeds the configured size limit")
    job_type = get_visible_job_type(
        session, job_type_id, principal=principal, for_update=True
    )
    if job_type is None:
        raise LookupError("Job Type not found")
    if job_type.status != JobTypeStatus.DRAFT.value:
        raise JobTypeStateConflict("Only draft Job Types accept handler uploads")

    artifact_id = str(uuid4())
    object_ref = (
        f"publishers/{job_type.publisher_id}/job-types/{job_type.id}/"
        f"artifacts/{artifact_id}.zip"
    )
    upload = storage.create_upload(
        object_ref=object_ref,
        expires_in_seconds=settings.handler_upload_url_seconds,
    )
    artifact = IdentityRepository(session).create_handler_artifact(
        artifact_id=artifact_id,
        job_type_id=job_type.id,
        object_ref=object_ref,
        expected_digest=expected_digest.lower(),
        expected_size_bytes=expected_size_bytes,
        upload_expires_at=upload.expires_at,
    )
    return artifact, upload.upload_url


def verify_handler_for_approval(
    session: Session,
    storage: MinioHandlerStorage,
    job_type_id: str,
    artifact_id: str,
    *,
    principal: AuthenticatedPrincipal,
) -> tuple[HandlerArtifact, JobType]:
    repository = IdentityRepository(session)
    job_type = get_visible_job_type(
        session, job_type_id, principal=principal, for_update=True
    )
    if job_type is None:
        raise LookupError("Job Type not found")
    artifact = repository.get_handler_artifact(
        artifact_id, job_type_id=job_type.id, for_update=True
    )
    if artifact is None:
        raise LookupError("Handler artifact not found")
    if artifact.status != HandlerArtifactStatus.PENDING.value:
        return artifact, job_type
    if job_type.status != JobTypeStatus.DRAFT.value:
        raise JobTypeStateConflict("Only draft Job Types can be activated")

    try:
        inspection = storage.inspect(
            object_ref=artifact.object_ref,
            expected_size_bytes=artifact.expected_size_bytes,
            max_size_bytes=load_settings().handler_max_bytes,
            max_uncompressed_bytes=load_settings().handler_max_uncompressed_bytes,
            expected_job_type=job_type.name,
        )
    except S3Error as exc:
        raise HandlerArtifactNotReady(
            "Handler artifact has not been uploaded"
        ) from exc

    artifact.actual_size_bytes = inspection.size_bytes
    artifact.actual_digest = inspection.digest
    rejection_reason = inspection.rejection_reason
    if inspection.digest is not None and inspection.digest != artifact.expected_digest:
        rejection_reason = "Handler artifact SHA-256 digest does not match its reservation"

    if rejection_reason is not None:
        artifact.status = HandlerArtifactStatus.REJECTED.value
        artifact.rejection_reason = rejection_reason
        try:
            storage.remove(artifact.object_ref)
        except S3Error:
            pass
        session.flush()
        return artifact, job_type

    artifact.status = HandlerArtifactStatus.VERIFIED.value
    artifact.verified_at = datetime.now(timezone.utc)
    artifact.rejection_reason = None
    verified_ref = (
        f"publishers/{job_type.publisher_id}/job-types/{job_type.id}/"
        f"verified/{artifact.actual_digest}.zip"
    )
    storage.promote(source_ref=artifact.object_ref, verified_ref=verified_ref)
    artifact.verified_ref = verified_ref
    job_type.status = JobTypeStatus.PENDING_APPROVAL.value
    session.flush()
    return artifact, job_type


def approve_handler_release(
    session: Session,
    job_type_id: str,
    artifact_id: str,
    *,
    admin_user_id: str,
) -> tuple[HandlerArtifact, JobType]:
    repository = IdentityRepository(session)
    job_type = repository.get_job_type(job_type_id, for_update=True)
    if job_type is None:
        raise LookupError("Job Type not found")
    artifact = repository.get_handler_artifact(
        artifact_id, job_type_id=job_type.id, for_update=True
    )
    if artifact is None:
        raise LookupError("Handler artifact not found")
    if artifact.status == HandlerArtifactStatus.APPROVED.value:
        return artifact, job_type
    if (
        artifact.status != HandlerArtifactStatus.VERIFIED.value
        or job_type.status != JobTypeStatus.PENDING_APPROVAL.value
        or not artifact.verified_ref
        or not artifact.actual_digest
    ):
        raise HandlerApprovalConflict("Handler release is not awaiting approval")

    settings = load_settings()
    if not settings.handler_signing_private_key:
        raise HandlerSigningUnavailable("Handler signing key is not configured")
    try:
        signature = sign_release(
            settings.handler_signing_private_key,
            job_type_id=job_type.id,
            job_type=job_type.name,
            version=job_type.version,
            digest=artifact.actual_digest,
        )
    except HandlerSigningError as exc:
        raise HandlerSigningUnavailable(str(exc)) from exc

    now = datetime.now(timezone.utc)
    artifact.status = HandlerArtifactStatus.APPROVED.value
    artifact.approved_by_user_id = admin_user_id
    artifact.approved_at = now
    artifact.signing_key_id = settings.handler_signing_key_id
    artifact.release_signature = signature
    artifact.rejection_reason = None
    job_type.handler_ref = artifact.verified_ref
    job_type.handler_digest = artifact.actual_digest
    job_type.handler_signing_key_id = settings.handler_signing_key_id
    job_type.handler_release_signature = signature
    job_type.status = JobTypeStatus.ACTIVE.value
    session.flush()
    return artifact, job_type


def reject_handler_release(
    session: Session,
    job_type_id: str,
    artifact_id: str,
    *,
    admin_user_id: str,
    reason: str,
) -> tuple[HandlerArtifact, JobType]:
    repository = IdentityRepository(session)
    job_type = repository.get_job_type(job_type_id, for_update=True)
    if job_type is None:
        raise LookupError("Job Type not found")
    artifact = repository.get_handler_artifact(
        artifact_id, job_type_id=job_type.id, for_update=True
    )
    if artifact is None:
        raise LookupError("Handler artifact not found")
    if (
        artifact.status != HandlerArtifactStatus.VERIFIED.value
        or job_type.status != JobTypeStatus.PENDING_APPROVAL.value
    ):
        raise HandlerApprovalConflict("Handler release is not awaiting approval")
    artifact.status = HandlerArtifactStatus.REJECTED.value
    artifact.rejection_reason = reason.strip()
    artifact.rejected_by_user_id = admin_user_id
    artifact.rejected_at = datetime.now(timezone.utc)
    job_type.status = JobTypeStatus.DRAFT.value
    session.flush()
    return artifact, job_type
