from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch
from stonks_cli.vnext.crypto_venues import (
    CryptoResearchVenue,
    CryptoVenueAssetSupport,
    filter_crypto_universe_by_supported_venues,
)
from stonks_cli.vnext.errors import VNextExternalDataError


def test_crypto_venue_filter_keeps_only_assets_with_observed_supported_venue_evidence():
    bitcoin = CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 50_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC))
    tether = CryptoMarketCapAsset("tether", "USDT", "Tether", 100_000_000_000.0, 20_000_000_000.0, 2, datetime(2026, 7, 14, tzinfo=UTC))
    support = CryptoVenueAssetSupport(CryptoResearchVenue.HYPERLIQUID, frozenset({"bitcoin"}), datetime(2026, 7, 14, tzinfo=UTC))

    assert filter_crypto_universe_by_supported_venues(
        CryptoMarketCapBatch("fixture", (bitcoin, tether)),
        (support,),
        frozenset({CryptoResearchVenue.HYPERLIQUID}),
    ) == (bitcoin,)


def test_crypto_venue_filter_fails_closed_when_supported_venue_evidence_is_missing_or_malformed():
    batch = CryptoMarketCapBatch(
        "fixture",
        (CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 50_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC)),),
    )

    with pytest.raises(VNextExternalDataError):
        filter_crypto_universe_by_supported_venues(batch, (), frozenset({CryptoResearchVenue.HYPERLIQUID}))
    with pytest.raises((TypeError, ValueError)):
        CryptoVenueAssetSupport(CryptoResearchVenue.HYPERLIQUID, frozenset(), datetime(2026, 7, 14, tzinfo=UTC))
