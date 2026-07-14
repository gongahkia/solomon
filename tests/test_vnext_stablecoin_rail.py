from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset
from stonks_cli.vnext.stablecoin_rail import StablecoinRailAllocation
from stonks_cli.vnext.stablecoins import StablecoinClassification, StablecoinStatus


def test_stablecoin_rail_allocation_accepts_classified_stablecoin_amount():
    asset = CryptoMarketCapAsset("tether", "USDT", "Tether", 1.0, 1.0, 1, datetime(2026, 7, 14, tzinfo=UTC))
    allocation = StablecoinRailAllocation("100", StablecoinClassification(asset, StablecoinStatus.STABLECOIN), 100.0)
    assert allocation.amount_usd == 100.0


def test_stablecoin_rail_allocation_fails_closed_for_unclassified_or_invalid_amount():
    asset = CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 1.0, 1.0, 1, datetime(2026, 7, 14, tzinfo=UTC))
    with pytest.raises(ValueError, match="classification"):
        StablecoinRailAllocation("100", StablecoinClassification(asset, StablecoinStatus.UNCLASSIFIED), 100.0)
    with pytest.raises(ValueError, match="amount"):
        StablecoinRailAllocation("100", StablecoinClassification(asset, StablecoinStatus.STABLECOIN), -1.0)
