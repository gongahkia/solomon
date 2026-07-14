from datetime import date

import pytest

from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.price_data import CanonicalDailyClose, CanonicalPriceSeries, fetch_canonical_daily_closes


def test_canonical_price_provider_returns_complete_ordered_usd_daily_series():
    closes = (CanonicalDailyClose(date(2026, 7, 13), 100.0), CanonicalDailyClose(date(2026, 7, 14), 101.0))

    class Provider:
        provider_id = "coingecko"

        def list_daily_closes(self, provider_asset_id, start, end):
            assert (provider_asset_id, start, end) == ("bitcoin", date(2026, 7, 13), date(2026, 7, 14))
            return closes

    assert fetch_canonical_daily_closes(Provider(), "bitcoin", date(2026, 7, 13), date(2026, 7, 14)) == CanonicalPriceSeries(
        "coingecko", "bitcoin", closes
    )


def test_canonical_price_provider_fails_closed_for_missing_days_or_malformed_closes():
    class Provider:
        provider_id = "coingecko"

        def list_daily_closes(self, provider_asset_id, start, end):
            return (CanonicalDailyClose(date(2026, 7, 13), 100.0),)

    with pytest.raises(VNextExternalDataError, match="incomplete"):
        fetch_canonical_daily_closes(Provider(), "bitcoin", date(2026, 7, 13), date(2026, 7, 14))
    with pytest.raises(ValueError):
        CanonicalDailyClose(date(2026, 7, 14), float("nan"))
