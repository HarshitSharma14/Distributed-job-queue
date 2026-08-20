import pytest

from distributed_job_queue.domain.job import (
    InvalidJobTransition,
    JobStatus,
    transition_job,
)


def test_valid_job_lifecycle_transition():
    status = transition_job(JobStatus.CREATED, JobStatus.QUEUED)
    status = transition_job(status, JobStatus.RUNNING)
    status = transition_job(status, JobStatus.COMPLETED)

    assert status is JobStatus.COMPLETED


def test_retry_transition_returns_to_queue():
    assert transition_job(JobStatus.RUNNING, JobStatus.RETRY_WAIT) is JobStatus.RETRY_WAIT
    assert transition_job(JobStatus.RETRY_WAIT, JobStatus.QUEUED) is JobStatus.QUEUED


def test_invalid_transition_is_rejected():
    with pytest.raises(InvalidJobTransition, match="CREATED -> RUNNING"):
        transition_job(JobStatus.CREATED, JobStatus.RUNNING)


def test_terminal_status_cannot_transition():
    with pytest.raises(InvalidJobTransition):
        transition_job(JobStatus.COMPLETED, JobStatus.QUEUED)
