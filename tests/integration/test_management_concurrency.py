"""Real concurrent transactions exercise the control-plane consistency boundary."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy import delete, select
from distributed_job_queue.api.management_services import lock_queue, replay_dead_letter
from distributed_job_queue.auth.service import AuthenticatedPrincipal, CredentialKind
from distributed_job_queue.domain.identity import UserRole
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.models import (
    QueueControl,
    Job,
    OutboxEvent,
    AuditEvent,
    JobType,
    User,
    UserRoleAssignment,
)
from distributed_job_queue.persistence.repositories import (
    IdentityRepository,
    JobRepository,
)


def test_pause_serializes_with_concurrent_claim_handoff_and_survives_reconnect():
    queue = f"pause-{uuid4()}"
    started = Event()

    def claimant():
        with SessionFactory.begin() as session:
            started.set()
            return lock_queue(session, queue).paused

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with SessionFactory.begin() as session:
                control = lock_queue(session, queue)
                control.paused = True
                future = pool.submit(claimant)
                assert started.wait(5)
                assert not future.done()
            assert future.result(timeout=5) is True
        with SessionFactory() as session:
            assert session.get(QueueControl, queue).paused is True
        with SessionFactory.begin() as session:
            lock_queue(session, queue).paused = False
        with SessionFactory() as session:
            assert session.get(QueueControl, queue).paused is False
    finally:
        with SessionFactory.begin() as session:
            session.execute(delete(QueueControl).where(QueueControl.queue == queue))


def test_concurrent_replay_creates_one_new_job_and_outbox_event():
    with SessionFactory.begin() as session:
        identities = IdentityRepository(session)
        user = identities.create_user(
            email=f"concurrent-{uuid4()}@example.com",
            display_name="Concurrent Producer",
        )
        identities.assign_role(user, UserRole.PRODUCER)
        jt = identities.create_job_type(
            publisher_id=user.id, name="replay", queue="replay"
        )
        job = JobRepository(session).create(
            job_type="replay",
            job_type_id=jt.id,
            publisher_id=user.id,
            producer_id=user.id,
            queue="replay",
            payload={"a": 1},
        )
        job.status = "DEAD_LETTERED"
        job.dead_lettered_at = datetime.now(timezone.utc)
        user_id, jt_id, job_id = user.id, jt.id, job.id
    principal = AuthenticatedPrincipal(
        user_id=user_id,
        email="test@example.com",
        display_name="Producer",
        roles=frozenset({UserRole.PRODUCER}),
        credential_kind=CredentialKind.BROWSER_SESSION,
    )

    def replay():
        with SessionFactory.begin() as session:
            result, replayed = replay_dead_letter(
                session, job_id, principal, "concurrent-key"
            )
            return result.id, replayed

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: replay(), range(2)))
        assert results[0][0] == results[1][0]
        assert sorted(r[1] for r in results) == [False, True]
        with SessionFactory() as session:
            assert (
                len(
                    list(
                        session.scalars(
                            select(OutboxEvent).where(
                                OutboxEvent.job_id == results[0][0]
                            )
                        )
                    )
                )
                == 1
            )
            assert session.get(Job, job_id).status == "DEAD_LETTERED"
    finally:
        with SessionFactory.begin() as session:
            ids = list(
                session.scalars(select(Job.id).where(Job.producer_id == user_id))
            )
            session.execute(delete(AuditEvent).where(AuditEvent.actor_id == user_id))
            session.execute(delete(OutboxEvent).where(OutboxEvent.job_id.in_(ids)))
            session.execute(delete(Job).where(Job.replay_of_job_id == job_id))
            session.execute(delete(Job).where(Job.id == job_id))
            session.execute(delete(JobType).where(JobType.id == jt_id))
            session.execute(
                delete(UserRoleAssignment).where(UserRoleAssignment.user_id == user_id)
            )
            session.execute(delete(User).where(User.id == user_id))
