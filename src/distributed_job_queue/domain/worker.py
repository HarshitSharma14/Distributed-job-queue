"""Worker health domain values."""

from enum import StrEnum


class WorkerStatus(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
