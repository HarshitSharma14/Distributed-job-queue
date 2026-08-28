"""Persistence operations for users, roles, and job-type definitions."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from distributed_job_queue.domain.identity import (
    HandlerArtifactStatus,
    JobTypeStatus,
    UserRole,
    UserStatus,
)
from distributed_job_queue.persistence.models import (
    HandlerArtifact,
    JobType,
    User,
    UserRoleAssignment,
)


class IdentityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_user(
        self, *, email: str, display_name: str, password_hash: str | None = None
    ) -> User:
        user = User(
            email=email.strip().lower(),
            display_name=display_name.strip(),
            password_hash=password_hash,
            status=UserStatus.ACTIVE.value,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def get_user_with_roles(self, user_id: str) -> User | None:
        statement = (
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.roles))
        )
        return self.session.scalars(statement).one_or_none()

    def assign_role(self, user: User, role: UserRole) -> UserRoleAssignment:
        existing = self.session.get(
            UserRoleAssignment, {"user_id": user.id, "role": role.value}
        )
        if existing is not None:
            return existing
        assignment = UserRoleAssignment(user_id=user.id, role=role.value)
        self.session.add(assignment)
        self.session.flush()
        return assignment

    def create_job_type(
        self,
        *,
        publisher_id: str,
        name: str,
        queue: str,
        version: int = 1,
        handler_ref: str | None = None,
        handler_digest: str | None = None,
        status: JobTypeStatus = JobTypeStatus.ACTIVE,
    ) -> JobType:
        job_type = JobType(
            publisher_id=publisher_id,
            name=name,
            version=version,
            queue=queue,
            status=status.value,
            handler_ref=handler_ref,
            handler_digest=handler_digest,
        )
        self.session.add(job_type)
        self.session.flush()
        return job_type

    def get_job_type(
        self, job_type_id: str, *, for_update: bool = False
    ) -> JobType | None:
        statement = select(JobType).where(JobType.id == job_type_id)
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalars(statement).one_or_none()

    def list_job_types(
        self, *, publisher_id: str | None = None, limit: int = 100
    ) -> list[JobType]:
        statement = select(JobType)
        if publisher_id is not None:
            statement = statement.where(JobType.publisher_id == publisher_id)
        statement = statement.order_by(
            JobType.created_at.desc(), JobType.name, JobType.version.desc()
        ).limit(limit)
        return list(self.session.scalars(statement))

    def get_owned_job_type(
        self,
        job_type_id: str,
        *,
        publisher_id: str,
        for_update: bool = False,
    ) -> JobType | None:
        statement = select(JobType).where(
            JobType.id == job_type_id,
            JobType.publisher_id == publisher_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalars(statement).one_or_none()

    def disable_job_type(self, job_type: JobType) -> JobType:
        job_type.status = JobTypeStatus.DISABLED.value
        self.session.flush()
        return job_type

    def create_handler_artifact(
        self,
        *,
        artifact_id: str,
        job_type_id: str,
        object_ref: str,
        expected_digest: str,
        expected_size_bytes: int,
        upload_expires_at: datetime,
    ) -> HandlerArtifact:
        artifact = HandlerArtifact(
            id=artifact_id,
            job_type_id=job_type_id,
            object_ref=object_ref,
            expected_digest=expected_digest,
            expected_size_bytes=expected_size_bytes,
            upload_expires_at=upload_expires_at,
            status=HandlerArtifactStatus.PENDING.value,
        )
        self.session.add(artifact)
        self.session.flush()
        return artifact

    def get_handler_artifact(
        self, artifact_id: str, *, job_type_id: str, for_update: bool = False
    ) -> HandlerArtifact | None:
        statement = select(HandlerArtifact).where(
            HandlerArtifact.id == artifact_id,
            HandlerArtifact.job_type_id == job_type_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalars(statement).one_or_none()
