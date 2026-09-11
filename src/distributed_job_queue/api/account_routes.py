"""Admin-managed accounts and mandatory password replacement."""

from typing import Annotated
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from distributed_job_queue.api.auth_dependencies import (
    require_admin_principal,
    require_admin_write_principal,
    require_csrf,
)
from distributed_job_queue.api.auth_schemas import EMAIL_PATTERN
from distributed_job_queue.api.dependencies import get_session
from distributed_job_queue.api.errors import APIError
from distributed_job_queue.api.management_services import audit, revoke_user_access
from distributed_job_queue.auth.security import hash_password, verify_password
from distributed_job_queue.auth.service import AuthenticatedPrincipal
from distributed_job_queue.domain.identity import UserRole, UserStatus
from distributed_job_queue.demo.accounts import is_public_demo_account
from distributed_job_queue.persistence.models import (
    User,
    UserRoleAssignment,
    BrowserSession,
    AuditEvent,
)

router = APIRouter(tags=["accounts"])
DB = Annotated[Session, Depends(get_session)]
Admin = Annotated[AuthenticatedPrincipal, Depends(require_admin_principal)]
AdminWrite = Annotated[AuthenticatedPrincipal, Depends(require_admin_write_principal)]


class UserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320, pattern=EMAIL_PATTERN)
    display_name: str = Field(min_length=1, max_length=200)
    roles: list[UserRole] = Field(min_length=1)
    status: UserStatus = UserStatus.ACTIVE


class CreateUserInput(UserInput):
    temporary_password: str = Field(min_length=12, max_length=1024)


class ResetPasswordInput(BaseModel):
    temporary_password: str = Field(min_length=12, max_length=1024)


class PasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


def user_data(user: User):
    return dict(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        roles=sorted(r.role for r in user.roles),
        status=user.status,
        password_change_required=user.password_change_required,
        created_at=user.created_at,
    )


@router.get("/admin/users")
def list_users(
    session: DB,
    principal: Admin,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
):
    stmt = (
        select(User)
        .where(User.password_hash.is_not(None))
        .order_by(User.id)
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(User.id > cursor)
    rows = list(session.scalars(stmt))
    return {
        "items": [user_data(row) for row in rows[:limit]],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    }


@router.post("/admin/users", status_code=201)
def create_user(body: CreateUserInput, session: DB, principal: AdminWrite):
    try:
        with session.begin_nested():
            user = User(
                email=body.email.strip().lower(),
                display_name=body.display_name.strip(),
                status=body.status.value,
                password_hash=hash_password(body.temporary_password),
                password_change_required=True,
            )
            user.roles = [UserRoleAssignment(role=r.value) for r in set(body.roles)]
            session.add(user)
            session.flush()
    except IntegrityError as exc:
        raise APIError(
            status_code=409,
            code="EMAIL_EXISTS",
            message="An account with that email already exists",
        ) from exc
    audit(
        session,
        principal.user_id,
        "user.create",
        user.id,
        roles=sorted(r.value for r in set(body.roles)),
    )
    return user_data(user)


@router.put("/admin/users/{user_id}")
def edit_user(user_id: UUID, body: UserInput, session: DB, principal: AdminWrite):
    # Serialize all Admin membership changes, including changes to different users.
    session.execute(text("SELECT pg_advisory_xact_lock(81472930)"))
    user = session.scalar(
        select(User)
        .where(User.id == str(user_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not user:
        raise APIError(status_code=404, code="USER_NOT_FOUND", message="User not found")
    if user.password_hash is None:
        raise APIError(
            status_code=403,
            code="SYSTEM_ACCOUNT",
            message="Historical system identities cannot be edited",
        )
    old_roles = {r.role for r in user.roles}
    roles = {r.value for r in body.roles}
    if (
        user.status == "ACTIVE"
        and "ADMIN" in old_roles
        and (body.status != UserStatus.ACTIVE or "ADMIN" not in roles)
    ):
        others = session.scalar(
            select(User.id)
            .join(UserRoleAssignment)
            .where(
                User.id != user.id,
                User.status == "ACTIVE",
                User.password_hash.is_not(None),
                UserRoleAssignment.role == "ADMIN",
            )
            .limit(1)
        )
        if not others:
            raise APIError(
                status_code=409,
                code="LAST_ADMIN",
                message="Keep at least one active Admin",
            )
    try:
        with session.begin_nested():
            user.email = body.email.strip().lower()
            user.display_name = body.display_name.strip()
            user.status = body.status.value
            user.roles[:] = [r for r in user.roles if r.role in roles]
            user.roles.extend(UserRoleAssignment(role=r) for r in roles - old_roles)
            if body.status != UserStatus.ACTIVE or old_roles - roles:
                revoke_user_access(session, user.id)
            session.flush()
    except IntegrityError as exc:
        raise APIError(
            status_code=409,
            code="EMAIL_EXISTS",
            message="An account with that email already exists",
        ) from exc
    audit(
        session,
        principal.user_id,
        "user.update",
        user.id,
        roles=sorted(roles),
        status=user.status,
    )
    return user_data(user)


@router.post("/admin/users/{user_id}/reset-password", status_code=204)
def reset_password(
    user_id: UUID, body: ResetPasswordInput, session: DB, principal: AdminWrite
):
    user = session.scalar(select(User).where(User.id == str(user_id)).with_for_update())
    if not user:
        raise APIError(status_code=404, code="USER_NOT_FOUND", message="User not found")
    user.password_hash = hash_password(body.temporary_password)
    user.password_change_required = True
    revoke_user_access(session, user.id)
    audit(session, principal.user_id, "user.reset_password", user.id)
    return Response(status_code=204)


@router.post("/auth/password", status_code=204)
def change_password(
    body: PasswordInput,
    session: DB,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_csrf)],
):
    user = session.scalar(
        select(User).where(User.id == principal.user_id).with_for_update()
    )
    if is_public_demo_account(user.email):
        raise APIError(
            status_code=403,
            code="SHARED_DEMO_ACCOUNT",
            message="The shared demo account password cannot be changed",
        )
    if not verify_password(user.password_hash, body.current_password):
        raise APIError(
            status_code=400,
            code="INVALID_PASSWORD",
            message="Current password is incorrect",
        )
    if body.current_password == body.new_password:
        raise APIError(
            status_code=400,
            code="PASSWORD_UNCHANGED",
            message="Choose a different password",
        )
    user.password_hash = hash_password(body.new_password)
    user.password_change_required = False
    session.execute(
        update(BrowserSession)
        .where(
            BrowserSession.user_id == user.id,
            BrowserSession.id != principal.browser_session.id,
            BrowserSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    audit(session, principal.user_id, "user.change_password", user.id)
    return Response(status_code=204)


@router.get("/admin/audit")
def list_audit(
    session: DB,
    principal: Admin,
    target_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
):
    stmt = select(AuditEvent).order_by(AuditEvent.id).limit(limit + 1)
    if target_id:
        stmt = stmt.where(AuditEvent.target_id == target_id)
    if cursor:
        stmt = stmt.where(AuditEvent.id > cursor)
    rows = list(session.scalars(stmt))
    return {
        "items": [
            dict(
                id=r.id,
                actor_id=r.actor_id,
                action=r.action,
                target_id=r.target_id,
                details=r.details,
                created_at=r.created_at,
            )
            for r in rows[:limit]
        ],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    }
