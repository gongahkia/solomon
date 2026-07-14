from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch
from stonks_cli.vnext.market_data_provenance import MarketDataProvenance, attach_market_data_provenance


def test_market_data_provenance_attaches_a_secret_safe_source_to_batch():
    batch = CryptoMarketCapBatch(
        "coingecko",
        (CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 50_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC)),),
    )
    provenance = MarketDataProvenance(
        "coingecko",
        "https://api.coingecko.com/api/v3/coins/markets",
        datetime(2026, 7, 14, tzinfo=UTC),
        "0" * 64,
    )

    assert attach_market_data_provenance(batch, provenance).provenance == provenance


@pytest.mark.parametrize(
    "source_url",
    ["http://api.coingecko.com/api/v3/coins/markets", "https://key@api.coingecko.com/markets", "https://api.coingecko.com/markets?api_key=secret"],
)
def test_market_data_provenance_fails_closed_for_unsafe_source_or_provider_mismatch(source_url):
    with pytest.raises(ValueError):
        MarketDataProvenance("coingecko", source_url, datetime(2026, 7, 14, tzinfo=UTC), "0" * 64)
    batch = CryptoMarketCapBatch(
        "coingecko",
        (CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 50_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC)),),
    )
    with pytest.raises(ValueError, match="does not match"):
        attach_market_data_provenance(
            batch,
            MarketDataProvenance("other", "https://example.com/markets", datetime(2026, 7, 14, tzinfo=UTC), "0" * 64),
        )
