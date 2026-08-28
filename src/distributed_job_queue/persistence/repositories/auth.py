"""Persistence operations for human-user authentication sessions."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from distributed_job_queue.persistence.models import BrowserSession, ProducerCredential, User


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

    def create_producer_credential(
        self,
        *,
        user_id: str,
        name: str,
        key_prefix: str,
        key_hash: str,
        scopes: list[str],
        expires_at: datetime,
    ) -> ProducerCredential:
        credential = ProducerCredential(
            user_id=user_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes=scopes,
            expires_at=expires_at,
        )
        self.session.add(credential)
        self.session.flush()
        return credential

    def get_active_producer_credential(
        self, key_hash: str, *, now: datetime
    ) -> ProducerCredential | None:
        statement = (
            select(ProducerCredential)
            .where(
                ProducerCredential.key_hash == key_hash,
                ProducerCredential.revoked_at.is_(None),
                ProducerCredential.expires_at > now,
            )
            .options(
                selectinload(ProducerCredential.user).selectinload(User.roles)
            )
        )
        return self.session.scalars(statement).one_or_none()

    def list_producer_credentials(self, user_id: str) -> list[ProducerCredential]:
        statement = (
            select(ProducerCredential)
            .where(ProducerCredential.user_id == user_id)
            .order_by(ProducerCredential.created_at.desc())
        )
        return list(self.session.scalars(statement))

    def get_owned_producer_credential(
        self, credential_id: str, *, user_id: str
    ) -> ProducerCredential | None:
        statement = select(ProducerCredential).where(
            ProducerCredential.id == credential_id,
            ProducerCredential.user_id == user_id,
        )
        return self.session.scalars(statement).one_or_none()

    def revoke_producer_credential(
        self, credential: ProducerCredential, *, now: datetime
    ) -> None:
        if credential.revoked_at is None:
            credential.revoked_at = now
            self.session.flush()
