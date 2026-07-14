from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from stonks_cli.vnext.foundation import FrozenUTCClock, SystemUTCClock, as_utc


def test_system_utc_clock_returns_aware_utc_time():
    timestamp = SystemUTCClock().now()

    assert timestamp.tzinfo is UTC
    assert timestamp.utcoffset() == timedelta(0)


def test_frozen_utc_clock_normalizes_time_and_is_deterministic():
    clock = FrozenUTCClock(datetime(2026, 7, 14, 10, 0, tzinfo=timezone(timedelta(hours=8))))

    assert clock.now() == datetime(2026, 7, 14, 2, 0, tzinfo=UTC)
    assert clock.now() == clock.now()


@pytest.mark.parametrize("value", [datetime(2026, 7, 14, 2, 0), "2026-07-14T02:00:00Z", None])
def test_utc_conversion_rejects_naive_and_malformed_values(value):
    with pytest.raises((TypeError, ValueError)):
        as_utc(value)
