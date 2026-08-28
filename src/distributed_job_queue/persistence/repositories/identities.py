"""Persistence operations for users, roles, and job-type definitions."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from distributed_job_queue.domain.identity import JobTypeStatus, UserRole, UserStatus
from distributed_job_queue.persistence.models import JobType, User, UserRoleAssignment


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
    ) -> JobType:
        job_type = JobType(
            publisher_id=publisher_id,
            name=name,
            version=version,
            queue=queue,
            status=JobTypeStatus.ACTIVE.value,
            handler_ref=handler_ref,
            handler_digest=handler_digest,
        )
        self.session.add(job_type)
        self.session.flush()
        return job_type

    def get_job_type(self, job_type_id: str) -> JobType | None:
        return self.session.get(JobType, job_type_id)
