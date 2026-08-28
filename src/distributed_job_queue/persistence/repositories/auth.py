"""Persistence operations for human-user authentication sessions."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from distributed_job_queue.persistence.models import BrowserSession, User


class AuthRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_user_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email.strip().lower())
        return self.session.scalars(statement).one_or_none()

    def create_session(
        self,
        *,
        user_id: str,
        token_hash: str,
        csrf_token_hash: str,
        expires_at: datetime,
    ) -> BrowserSession:
        browser_session = BrowserSession(
            user_id=user_id,
            token_hash=token_hash,
            csrf_token_hash=csrf_token_hash,
            expires_at=expires_at,
        )
        self.session.add(browser_session)
        self.session.flush()
        return browser_session

    def get_active_session(
        self, token_hash: str, *, now: datetime
    ) -> BrowserSession | None:
        statement = (
            select(BrowserSession)
            .where(
                BrowserSession.token_hash == token_hash,
                BrowserSession.revoked_at.is_(None),
                BrowserSession.expires_at > now,
            )
            .options(
                selectinload(BrowserSession.user).selectinload(User.roles)
            )
        )
        return self.session.scalars(statement).one_or_none()

    def revoke_session(self, browser_session: BrowserSession, *, now: datetime) -> None:
        if browser_session.revoked_at is None:
            browser_session.revoked_at = now
            self.session.flush()
