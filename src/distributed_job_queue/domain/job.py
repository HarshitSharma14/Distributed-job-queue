"""Job lifecycle rules."""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"


class InvalidJobTransition(ValueError):
    """Raised when a job attempts an unsupported state transition."""


ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.CREATED: frozenset({JobStatus.QUEUED}),
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING}),
    JobStatus.RUNNING: frozenset(
        {JobStatus.COMPLETED, JobStatus.RETRY_WAIT, JobStatus.FAILED}
    ),
    JobStatus.RETRY_WAIT: frozenset({JobStatus.QUEUED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset({JobStatus.DEAD_LETTERED}),
    JobStatus.DEAD_LETTERED: frozenset(),
}


def transition_job(current: JobStatus, target: JobStatus) -> JobStatus:
    """Validate and return a job's next status."""

    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidJobTransition(
            f"Invalid job transition: {current.value} -> {target.value}"
        )
    return target
