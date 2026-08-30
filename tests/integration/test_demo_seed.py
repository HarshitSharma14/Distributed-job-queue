from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from distributed_job_queue.demo.seed import _demo_id, seed_demo_data
from distributed_job_queue.persistence.database import engine
from distributed_job_queue.persistence.models import Job, JobAttempt, JobType, User, Worker


def test_demo_seed_is_complete_and_idempotent():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    try:
        first = seed_demo_data(session, now=now)
        second = seed_demo_data(session, now=now)
        job_ids = [_demo_id("job", str(index)) for index in range(40)]

        assert first == second
        assert first.users == 4
        assert session.scalar(select(func.count()).select_from(Job).where(Job.id.in_(job_ids))) == 40
        assert session.scalar(select(func.count()).select_from(JobType).where(JobType.id.in_([_demo_id("job-type", "demo@relay.local:generate_report:1"), _demo_id("job-type", "demo@relay.local:send_email:1"), _demo_id("job-type", "publisher.media@relay.local:resize_image:1"), _demo_id("job-type", "publisher.media@relay.local:transcode_video:1")]))) == 4
        assert session.scalar(select(func.count()).select_from(Worker).where(Worker.id.like("demo-%"))) == 4
        assert session.scalar(select(func.count()).select_from(JobAttempt).where(JobAttempt.job_id.in_(job_ids))) > 30
        assert session.scalar(select(func.count()).select_from(User).where(User.email.like("%@relay.local"))) >= 4
    finally:
        session.close()
        transaction.rollback()
        connection.close()
