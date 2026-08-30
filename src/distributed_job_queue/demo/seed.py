"""Create deterministic local dashboard data without altering non-demo records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from distributed_job_queue.auth.security import hash_password
from distributed_job_queue.common.config import load_settings
from distributed_job_queue.domain.identity import JobTypeStatus, UserRole
from distributed_job_queue.domain.job import JobStatus
from distributed_job_queue.domain.worker import WorkerStatus
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.models import Job, JobAttempt, JobType, User, Worker
from distributed_job_queue.persistence.repositories import IdentityRepository

DEMO_PASSWORD = "relay-demo-password"
DEMO_EMAIL = "demo@relay.local"


@dataclass(frozen=True, slots=True)
class DemoSummary:
    users: int
    job_types: int
    workers: int
    jobs: int


def seed_demo_data(session: Session, *, now: datetime | None = None) -> DemoSummary:
    """Idempotently add a coherent demonstration dataset."""

    current_time = now or datetime.now(timezone.utc)
    identities = IdentityRepository(session)
    demo = _user(
        session,
        identities,
        email=DEMO_EMAIL,
        name="Demo Operator",
        roles=(UserRole.ADMIN, UserRole.PUBLISHER, UserRole.PRODUCER, UserRole.WORKER),
    )
    media_publisher = _user(
        session,
        identities,
        email="publisher.media@relay.local",
        name="Media Publisher",
        roles=(UserRole.PUBLISHER,),
    )
    studio_producer = _user(
        session,
        identities,
        email="producer.studio@relay.local",
        name="Studio Producer",
        roles=(UserRole.PRODUCER,),
    )
    delivery_worker = _user(
        session,
        identities,
        email="worker.delivery@relay.local",
        name="Delivery Worker Owner",
        roles=(UserRole.WORKER,),
    )

    job_types = (
        _job_type(session, demo, "generate_report", "reports"),
        _job_type(session, demo, "send_email", "email"),
        _job_type(session, media_publisher, "resize_image", "media"),
        _job_type(session, media_publisher, "transcode_video", "media"),
    )
    workers = (
        _worker(session, "demo-reports-01", demo, ["generate_report"], WorkerStatus.ONLINE, current_time),
        _worker(session, "demo-media-01", demo, ["resize_image", "transcode_video"], WorkerStatus.OFFLINE, current_time),
        _worker(session, "demo-email-01", delivery_worker, ["send_email"], WorkerStatus.ONLINE, current_time),
        _worker(session, "demo-media-02", delivery_worker, ["resize_image", "transcode_video"], WorkerStatus.ONLINE, current_time),
    )
    worker_by_type = {
        "generate_report": workers[0],
        "send_email": workers[2],
        "resize_image": workers[3],
        "transcode_video": workers[3],
    }
    producers = (demo, studio_producer)
    statuses = (
        JobStatus.COMPLETED,
        JobStatus.COMPLETED,
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.RETRY_WAIT,
        JobStatus.COMPLETED,
        JobStatus.DEAD_LETTERED,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.QUEUED,
    )
    for index in range(40):
        job_type = job_types[index % len(job_types)]
        producer = producers[index % len(producers)]
        _job(
            session,
            index=index,
            job_type=job_type,
            producer=producer,
            worker=worker_by_type[job_type.name],
            status=statuses[index % len(statuses)],
            now=current_time,
        )
    session.flush()
    return DemoSummary(users=4, job_types=4, workers=4, jobs=40)


def main() -> None:
    settings = load_settings()
    if settings.environment != "development":
        raise SystemExit("Demo data can only be seeded when APP_ENV=development")
    with SessionFactory.begin() as session:
        summary = seed_demo_data(session)
    print(
        f"Demo data ready: {summary.users} users, {summary.job_types} Job Types, "
        f"{summary.workers} Workers, {summary.jobs} jobs"
    )
    print(f"Login: {DEMO_EMAIL} / {DEMO_PASSWORD}")


def _demo_id(kind: str, value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"distributed-job-queue-demo:{kind}:{value}"))


def _user(
    session: Session,
    identities: IdentityRepository,
    *,
    email: str,
    name: str,
    roles: tuple[UserRole, ...],
) -> User:
    user = session.scalars(select(User).where(User.email == email)).one_or_none()
    if user is None:
        user = User(
            id=_demo_id("user", email),
            email=email,
            display_name=name,
            password_hash=hash_password(DEMO_PASSWORD),
            status="ACTIVE",
        )
        session.add(user)
        session.flush()
    for role in roles:
        identities.assign_role(user, role)
    return user


def _job_type(session: Session, publisher: User, name: str, queue: str) -> JobType:
    identifier = _demo_id("job-type", f"{publisher.email}:{name}:1")
    job_type = session.get(JobType, identifier)
    if job_type is None:
        job_type = JobType(
            id=identifier,
            publisher_id=publisher.id,
            name=name,
            version=1,
            queue=queue,
            status=JobTypeStatus.DISABLED.value,
        )
        session.add(job_type)
        session.flush()
    return job_type


def _worker(
    session: Session,
    identifier: str,
    owner: User,
    capabilities: list[str],
    status: WorkerStatus,
    now: datetime,
) -> Worker:
    worker = session.get(Worker, identifier)
    if worker is None:
        worker = Worker(
            id=identifier,
            owner_user_id=owner.id,
            capabilities=capabilities,
            status=status.value,
            registered_at=now - timedelta(days=14),
            last_heartbeat_at=(
                now - timedelta(seconds=8)
                if status == WorkerStatus.ONLINE
                else now - timedelta(hours=5)
            ),
        )
        session.add(worker)
        session.flush()
    return worker


def _job(
    session: Session,
    *,
    index: int,
    job_type: JobType,
    producer: User,
    worker: Worker,
    status: JobStatus,
    now: datetime,
) -> Job:
    identifier = _demo_id("job", str(index))
    existing = session.get(Job, identifier)
    if existing is not None:
        return existing
    created_at = now - timedelta(hours=(40 - index) * 2)
    attempts = _attempt_count(status, index)
    finished_at = created_at + timedelta(seconds=12 + index * 3)
    job = Job(
        id=identifier,
        job_type_id=job_type.id,
        publisher_id=job_type.publisher_id,
        producer_id=producer.id,
        type=job_type.name,
        queue=job_type.queue,
        payload={"demo": True, "record": index, "input": f"sample-{index:02d}"},
        priority=(index % 3) * 10,
        status=status.value,
        attempts=attempts,
        max_attempts=3,
        available_at=(
            now + timedelta(minutes=10 + index)
            if status == JobStatus.RETRY_WAIT
            else created_at
        ),
        created_at=created_at,
        updated_at=finished_at,
    )
    if status == JobStatus.RUNNING:
        job.worker_id = worker.id
        job.lease_token = _demo_id("lease", str(index))
        job.lease_expires_at = now + timedelta(minutes=20)
        job.updated_at = now - timedelta(seconds=20)
    elif status == JobStatus.COMPLETED:
        job.completed_at = finished_at
        job.result_ref = f"demo/results/{identifier}.json"
    elif status in {JobStatus.FAILED, JobStatus.RETRY_WAIT, JobStatus.DEAD_LETTERED}:
        job.error = {
            "type": "DemoDependencyError",
            "message": "Synthetic downstream timeout for dashboard demonstration",
        }
        if status == JobStatus.DEAD_LETTERED:
            job.dead_lettered_at = finished_at
    session.add(job)
    session.flush()
    for attempt_number in range(1, attempts + 1):
        is_latest = attempt_number == attempts
        attempt_status = _attempt_status(status, is_latest)
        started_at = created_at + timedelta(seconds=attempt_number * 5)
        session.add(
            JobAttempt(
                id=_demo_id("attempt", f"{index}:{attempt_number}"),
                job_id=job.id,
                worker_id=worker.id,
                lease_token=(job.lease_token if status == JobStatus.RUNNING and is_latest else None),
                attempt_number=attempt_number,
                started_at=started_at,
                finished_at=(None if attempt_status == JobStatus.RUNNING else started_at + timedelta(seconds=7 + index)),
                status=attempt_status.value,
                error=(
                    None
                    if attempt_status in {JobStatus.COMPLETED, JobStatus.RUNNING}
                    else {"type": "DemoDependencyError", "message": "Synthetic timeout"}
                ),
            )
        )
    return job


def _attempt_count(status: JobStatus, index: int) -> int:
    if status == JobStatus.QUEUED:
        return 0
    if status in {JobStatus.FAILED, JobStatus.DEAD_LETTERED}:
        return 3
    if status == JobStatus.RETRY_WAIT:
        return 2
    if status == JobStatus.COMPLETED and index % 4 == 1:
        return 2
    return 1


def _attempt_status(status: JobStatus, is_latest: bool) -> JobStatus:
    if not is_latest:
        return JobStatus.FAILED
    if status == JobStatus.COMPLETED:
        return JobStatus.COMPLETED
    if status == JobStatus.RUNNING:
        return JobStatus.RUNNING
    return JobStatus.FAILED


if __name__ == "__main__":
    main()
