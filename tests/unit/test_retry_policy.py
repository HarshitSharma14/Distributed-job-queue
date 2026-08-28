from datetime import datetime, timezone

import pytest

from distributed_job_queue.domain.retry import (
    retry_available_at,
    retry_delay_seconds,
)


def test_retry_delay_uses_exponential_backoff_plus_bounded_jitter():
    assert retry_delay_seconds(
        1,
        base_delay_seconds=5,
        max_delay_seconds=300,
        random_fraction=lambda: 0.5,
    ) == 7.5
    assert retry_delay_seconds(
        3,
        base_delay_seconds=5,
        max_delay_seconds=300,
        random_fraction=lambda: 0.5,
    ) == 22.5


def test_retry_delay_never_exceeds_maximum():
    assert retry_delay_seconds(
        20,
        base_delay_seconds=5,
        max_delay_seconds=300,
        random_fraction=lambda: 1,
    ) == 300


def test_retry_available_at_is_based_on_supplied_clock():
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)

    available_at = retry_available_at(
        now,
        2,
        base_delay_seconds=10,
        max_delay_seconds=300,
        random_fraction=lambda: 0,
    )

    assert available_at == datetime(2026, 8, 28, 0, 0, 20, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("attempt_number", "base_delay", "max_delay"),
    [(0, 5, 300), (1, -1, 300), (1, 5, -1)],
)
def test_retry_delay_rejects_invalid_configuration(
    attempt_number, base_delay, max_delay
):
    with pytest.raises(ValueError):
        retry_delay_seconds(
            attempt_number,
            base_delay_seconds=base_delay,
            max_delay_seconds=max_delay,
        )


def test_retry_delay_rejects_invalid_random_fraction():
    with pytest.raises(ValueError, match="between 0 and 1"):
        retry_delay_seconds(
            1,
            base_delay_seconds=5,
            max_delay_seconds=300,
            random_fraction=lambda: 1.1,
        )
