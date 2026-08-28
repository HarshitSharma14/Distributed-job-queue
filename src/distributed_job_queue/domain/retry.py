"""Retry timing policy independent of persistence and scheduling."""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import datetime, timedelta


def retry_delay_seconds(
    attempt_number: int,
    *,
    base_delay_seconds: int,
    max_delay_seconds: int,
    random_fraction: Callable[[], float] = random.random,
) -> float:
    """Return capped exponential backoff plus bounded positive jitter."""

    if attempt_number < 1:
        raise ValueError("attempt_number must be at least 1")
    if base_delay_seconds < 0:
        raise ValueError("base_delay_seconds must not be negative")
    if max_delay_seconds < 0:
        raise ValueError("max_delay_seconds must not be negative")

    exponential = min(
        max_delay_seconds,
        base_delay_seconds * (2 ** (attempt_number - 1)),
    )
    fraction = random_fraction()
    if not 0 <= fraction <= 1:
        raise ValueError("random_fraction must return a value between 0 and 1")
    jitter_window = min(
        base_delay_seconds,
        max(0, max_delay_seconds - exponential),
    )
    return exponential + (fraction * jitter_window)


def retry_available_at(
    now: datetime,
    attempt_number: int,
    *,
    base_delay_seconds: int,
    max_delay_seconds: int,
    random_fraction: Callable[[], float] = random.random,
) -> datetime:
    """Return the durable time at which a failed job becomes queueable."""

    return now + timedelta(
        seconds=retry_delay_seconds(
            attempt_number,
            base_delay_seconds=base_delay_seconds,
            max_delay_seconds=max_delay_seconds,
            random_fraction=random_fraction,
        )
    )
