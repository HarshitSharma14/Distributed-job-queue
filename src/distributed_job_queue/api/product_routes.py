"""Browser-ready catalog, transfers, replay and operational controls."""

import hashlib
import json
from io import BytesIO
from typing import Annotated
from uuid import UUID
from zipfile import ZipFile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from starlette.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from minio.error import S3Error
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from distributed_job_queue.api.auth_dependencies import (
    require_current_principal,
    require_publisher_principal,
    require_publisher_write_principal,
    require_job_read_principal,
    require_csrf,
    require_admin_principal,
    require_admin_write_principal,
)
from distributed_job_queue.api.dependencies import (
    get_session,
    get_handler_storage,
    get_result_storage,
)
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.api.job_type_services import (
    get_visible_job_type,
    reserve_handler_upload,
    verify_handler_for_approval,
    JobTypeStateConflict,
)
from distributed_job_queue.api.job_type_routes import _response, _verification_response
from distributed_job_queue.api.management_services import (
    audit,
    lock_queue,
    replay_dead_letter,
)
from distributed_job_queue.api.services import get_job_detail, _create_response
from distributed_job_queue.auth.service import AuthenticatedPrincipal
from distributed_job_queue.common.config import load_settings
from distributed_job_queue.common.metrics import JOBS_SUBMITTED
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.persistence.models import (
    JobType,
    HandlerArtifact,
    Worker,
    WorkerCredential,
    QueueControl,
    Job,
)
from distributed_job_queue.storage import MinioHandlerStorage, MinioResultStorage

router = APIRouter(tags=["dashboard workflows"])
DB = Annotated[Session, Depends(get_session)]
Human = Annotated[AuthenticatedPrincipal, Depends(require_current_principal)]
Publisher = Annotated[AuthenticatedPrincipal, Depends(require_publisher_principal)]
Admin = Annotated[AuthenticatedPrincipal, Depends(require_admin_principal)]
AdminWrite = Annotated[AuthenticatedPrincipal, Depends(require_admin_write_principal)]


@router.get("/catalog/job-types")
def catalog(
    session: DB,
    principal: Human,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
):
    if principal.roles.isdisjoint({UserRole.ADMIN, UserRole.PRODUCER, UserRole.WORKER}):
        raise APIError(
            status_code=403,
            code="CATALOG_FORBIDDEN",
            message="Producer or Worker role required",
        )
    stmt = (
        select(JobType)
        .where(
            JobType.status == "ACTIVE", JobType.handler_release_signature.is_not(None)
        )
        .order_by(JobType.id)
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(JobType.id > cursor)
    rows = list(session.scalars(stmt))
    return {
        "items": [
            dict(
                job_type_id=r.id,
                publisher_id=r.publisher_id,
                name=r.name,
                version=r.version,
                queue=r.queue,
                status=r.status,
            )
            for r in rows[:limit]
        ],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    }


@router.get("/management/job-types")
def managed_catalog(
    session: DB,
    principal: Publisher,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    status: str | None = None,
):
    stmt = select(JobType).order_by(JobType.id).limit(limit + 1)
    if UserRole.ADMIN not in principal.roles:
        stmt = stmt.where(JobType.publisher_id == principal.user_id)
    if cursor:
        stmt = stmt.where(JobType.id > cursor)
    if status:
        stmt = stmt.where(JobType.status == status)
    rows = list(session.scalars(stmt))
    return {
        "items": [_response(r) for r in rows[:limit]],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    }


@router.get("/job-types/{job_type_id}/artifacts")
def artifacts(
    job_type_id: UUID,
    session: DB,
    principal: Publisher,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
):
    job_type = get_visible_job_type(session, str(job_type_id), principal=principal)
    if not job_type:
        raise APIError(
            status_code=404, code="JOB_TYPE_NOT_FOUND", message="Job Type not found"
        )
    stmt = (
        select(HandlerArtifact)
        .where(HandlerArtifact.job_type_id == job_type.id)
        .order_by(HandlerArtifact.id)
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(HandlerArtifact.id > cursor)
    rows = list(session.scalars(stmt))
    return {
        "items": [_verification_response(a, job_type) for a in rows[:limit]],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    }


@router.get("/job-types/{job_type_id}/example.zip")
def example_bundle(job_type_id: UUID, session: DB, principal: Publisher):
    job_type = get_visible_job_type(session, str(job_type_id), principal=principal)
    if not job_type:
        raise APIError(
            status_code=404, code="JOB_TYPE_NOT_FOUND", message="Job Type not found"
        )
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"job_type": job_type.name, "entrypoint": "handler:run"}),
        )
        archive.writestr(
            "handler.py",
            'def run(payload):\n    """Return a JSON-serializable result. Standard library only."""\n    if payload.get("fail"):\n        raise ValueError("Requested demonstration failure")\n    return {"message": "Handler completed", "input": payload}\n',
        )
    return Response(
        output.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="example-handler.zip"'},
    )


@router.post("/job-types/{job_type_id}/upload")
async def upload_bundle(
    job_type_id: UUID,
    request: Request,
    session: DB,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_publisher_write_principal)
    ],
    storage: Annotated[MinioHandlerStorage, Depends(get_handler_storage)],
):
    limit = load_settings().handler_max_bytes
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > limit:
            raise APIError(
                status_code=413,
                code="HANDLER_TOO_LARGE",
                message="Handler archive exceeds the size limit",
            )
        data.extend(chunk)
    if not data:
        raise APIError(
            status_code=400, code="EMPTY_HANDLER", message="Choose a ZIP archive"
        )

    def store_and_verify():
        try:
            artifact, _ = reserve_handler_upload(
                session,
                storage,
                str(job_type_id),
                principal=principal,
                expected_digest=hashlib.sha256(data).hexdigest(),
                expected_size_bytes=len(data),
            )
            storage.client.put_object(
                storage.bucket,
                artifact.object_ref,
                BytesIO(data),
                len(data),
                content_type="application/zip",
            )
            artifact, job_type = verify_handler_for_approval(
                session, storage, str(job_type_id), artifact.id, principal=principal
            )
        except LookupError as exc:
            raise APIError(
                status_code=404, code="JOB_TYPE_NOT_FOUND", message="Job Type not found"
            ) from exc
        except JobTypeStateConflict as exc:
            raise APIError(
                status_code=409, code="JOB_TYPE_STATE_CONFLICT", message=str(exc)
            ) from exc
        audit(
            session,
            principal.user_id,
            "handler.upload",
            str(job_type_id),
            artifact_id=artifact.id,
            status=artifact.status,
        )
        return _verification_response(artifact, job_type)

    return await run_in_threadpool(store_and_verify)


@router.get("/jobs/{job_id}/result")
def download_result(
    job_id: UUID,
    session: DB,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_job_read_principal)],
    storage: Annotated[MinioResultStorage, Depends(get_result_storage)],
):
    detail = get_job_detail(session, str(job_id), principal=principal)
    if detail is None or detail.status != "COMPLETED" or not detail.result_ref:
        raise APIError(
            status_code=404, code="RESULT_NOT_FOUND", message="No result available"
        )
    try:
        obj = storage.client.get_object(storage.bucket, detail.result_ref)
    except S3Error as exc:
        raise APIError(
            status_code=404,
            code="RESULT_NOT_FOUND",
            message="Result object is unavailable",
        ) from exc

    def chunks():
        try:
            yield from obj.stream(64 * 1024)
        finally:
            obj.close()
            obj.release_conn()

    return StreamingResponse(
        chunks(),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="result-{job_id}.json"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/jobs/{job_id}/replay", status_code=202)
def replay(
    job_id: UUID,
    response: Response,
    session: DB,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_csrf)],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
):
    job, replayed = replay_dead_letter(session, str(job_id), principal, idempotency_key)
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    else:
        JOBS_SUBMITTED.labels(queue=job.queue).inc()
    return _create_response(job)


@router.get("/admin/queue-controls")
def queue_controls(session: DB, principal: Admin):
    return {
        r.queue: {
            "paused": r.paused,
            "updated_at": r.updated_at,
            "updated_by": r.updated_by,
        }
        for r in session.scalars(select(QueueControl))
    }


@router.post("/admin/queues/{queue}/pause")
def pause(queue: str, session: DB, principal: AdminWrite):
    return set_pause(session, principal, queue, True)


@router.post("/admin/queues/{queue}/resume")
def resume(queue: str, session: DB, principal: AdminWrite):
    return set_pause(session, principal, queue, False)


def set_pause(session, principal, queue, paused):
    exists = session.scalar(
        select(JobType.id).where(JobType.queue == queue).limit(1)
    ) or session.scalar(select(Job.id).where(Job.queue == queue).limit(1))
    if not exists:
        raise APIError(
            status_code=404, code="QUEUE_NOT_FOUND", message="Queue not found"
        )
    control = lock_queue(session, queue)
    control.paused = paused
    control.updated_at = datetime.now(timezone.utc)
    control.updated_by = principal.user_id
    audit(
        session, principal.user_id, "queue.pause" if paused else "queue.resume", queue
    )
    return {"queue": queue, "paused": paused}


@router.delete("/admin/workers/{worker_id}/credential", status_code=204)
def revoke_worker(worker_id: str, session: DB, principal: AdminWrite):
    if not session.get(Worker, worker_id):
        raise APIError(
            status_code=404, code="WORKER_NOT_FOUND", message="Worker not found"
        )
    session.execute(
        update(WorkerCredential)
        .where(
            WorkerCredential.worker_id == worker_id,
            WorkerCredential.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    audit(session, principal.user_id, "worker.revoke", worker_id)
    return Response(status_code=204)


@router.get("/worker-management/startup")
def worker_startup(principal: Human):
    if UserRole.WORKER not in principal.roles:
        raise APIError(
            status_code=403, code="WORKER_ROLE_REQUIRED", message="Worker role required"
        )
    settings = load_settings()
    return {
        "trusted_public_keys": json.loads(settings.handler_trusted_public_keys),
        "sandbox_image": settings.handler_sandbox_image,
    }
