from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.crypto_liquidity import filter_crypto_universe_by_liquidity
from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch


def test_crypto_liquidity_filter_keeps_assets_at_or_above_usd_threshold():
    bitcoin = CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 50_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC))
    illiquid = CryptoMarketCapAsset("illiquid", "ILL", "Illiquid", 1_000_000.0, 10.0, 2, datetime(2026, 7, 14, tzinfo=UTC))

    assert filter_crypto_universe_by_liquidity(CryptoMarketCapBatch("fixture", (bitcoin, illiquid)), 1_000.0) == (bitcoin,)


@pytest.mark.parametrize("threshold", [-1.0, float("nan"), 1])
def test_crypto_liquidity_filter_rejects_malformed_thresholds(threshold):
    batch = CryptoMarketCapBatch(
        "fixture",
        (CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 50_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC)),),
    )

    with pytest.raises(ValueError):
        filter_crypto_universe_by_liquidity(batch, threshold)


@pytest.mark.parametrize("volume", [-1.0, float("nan"), 1])
def test_crypto_market_cap_contract_rejects_missing_or_malformed_usd_volume(volume):
    with pytest.raises((TypeError, ValueError)):
        CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, volume, 1, datetime(2026, 7, 14, tzinfo=UTC))
