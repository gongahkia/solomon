from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.exchange_time import ExchangeTimeZone, normalize_exchange_timestamp


def test_normalize_exchange_timestamp_converts_us_eastern_and_singapore_to_utc():
    assert normalize_exchange_timestamp("2026-07-01 09:30:00", ExchangeTimeZone.US_EASTERN) == datetime(2026, 7, 1, 13, 30, tzinfo=UTC)
    assert normalize_exchange_timestamp("2026-07-01 09:00:00", ExchangeTimeZone.SINGAPORE) == datetime(2026, 7, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("value", ["2026-03-08 02:30:00", "2026-11-01 01:30:00", "2026-07-01"])
def test_normalize_exchange_timestamp_rejects_nonexistent_ambiguous_or_malformed_us_times(value):
    with pytest.raises(ValueError):
        normalize_exchange_timestamp(value, ExchangeTimeZone.US_EASTERN)
