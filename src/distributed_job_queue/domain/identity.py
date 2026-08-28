"""Identity and job-type catalog concepts."""

from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    PUBLISHER = "PUBLISHER"
    PRODUCER = "PRODUCER"
    WORKER = "WORKER"


class JobTypeStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


# Temporary ownership used by the unauthenticated API until user authentication lands.
BOOTSTRAP_USER_ID = "00000000-0000-0000-0000-000000000001"
BOOTSTRAP_JOB_TYPE_ID = "00000000-0000-0000-0000-000000000002"
