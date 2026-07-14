from datetime import UTC, date, datetime

import pytest

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch
from stonks_cli.vnext.daily_closing_prices import ingest_daily_closing_prices
from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.price_data import CanonicalDailyClose


def test_daily_closing_price_ingestion_requires_complete_series_for_every_batch_asset():
    batch = CryptoMarketCapBatch(
        "fixture",
        (
            CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 50_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC)),
            CryptoMarketCapAsset("ethereum", "ETH", "Ethereum", 400_000_000_000.0, 20_000_000_000.0, 2, datetime(2026, 7, 14, tzinfo=UTC)),
        ),
    )

    class Provider:
        provider_id = "fixture"

        def list_daily_closes(self, provider_asset_id, start, end):
            return (CanonicalDailyClose(date(2026, 7, 13), 100.0), CanonicalDailyClose(date(2026, 7, 14), 101.0))

    ingestion = ingest_daily_closing_prices(batch, Provider(), date(2026, 7, 13), date(2026, 7, 14))

    assert [item.provider_asset_id for item in ingestion.series] == ["bitcoin", "ethereum"]


def test_daily_closing_price_ingestion_fails_closed_for_provider_or_series_failure():
    batch = CryptoMarketCapBatch(
        "fixture",
        (CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 50_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC)),),
    )

    class WrongProvider:
        provider_id = "other"

    with pytest.raises(VNextExternalDataError):
        ingest_daily_closing_prices(batch, WrongProvider(), date(2026, 7, 13), date(2026, 7, 14))
