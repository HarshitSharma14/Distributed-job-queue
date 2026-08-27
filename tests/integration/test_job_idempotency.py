import threading
import time
from uuid import uuid4

from sqlalchemy import delete, select

from distributed_job_queue.api.schemas import JobCreateRequest
from distributed_job_queue.api.services import submit_job
from distributed_job_queue.persistence.database import SessionFactory
from distributed_job_queue.persistence.models import Job


def test_concurrent_submissions_with_same_key_create_one_job():
    idempotency_key = f"concurrent-{uuid4()}"
    request = JobCreateRequest(
        type="generate_report",
        queue="reports",
        payload={"report_id": 42},
    )
    first_session = SessionFactory()
    first_transaction = first_session.begin()
    first = submit_job(
        first_session, request, idempotency_key=idempotency_key
    )
    second_result = []
    second_error = []

    def submit_concurrently() -> None:
        try:
            with SessionFactory.begin() as session:
                second_result.append(
                    submit_job(
                        session, request, idempotency_key=idempotency_key
                    )
                )
        except Exception as exc:
            second_error.append(exc)

    thread = threading.Thread(target=submit_concurrently, daemon=True)
    thread.start()
    time.sleep(0.1)
    first_transaction.commit()
    thread.join(timeout=5)

    try:
        assert thread.is_alive() is False
        assert second_error == []
        assert len(second_result) == 1
        assert second_result[0].replayed is True
        assert second_result[0].response.job_id == first.response.job_id
        with SessionFactory() as session:
            jobs = list(
                session.scalars(
                    select(Job).where(Job.idempotency_key == idempotency_key)
                )
            )
            assert len(jobs) == 1
    finally:
        first_session.close()
        with SessionFactory.begin() as session:
            session.execute(
                delete(Job).where(Job.idempotency_key == idempotency_key)
            )
