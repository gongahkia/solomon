from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.crypto_market_cap import (
    CryptoMarketCapAsset,
    CryptoMarketCapBatch,
    fetch_crypto_market_caps,
)
from stonks_cli.vnext.errors import VNextExternalDataError


def test_crypto_market_cap_provider_contract_returns_complete_ranked_batch():
    assets = (
        CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC)),
        CryptoMarketCapAsset("ethereum", "ETH", "Ethereum", 400_000_000_000.0, 2, datetime(2026, 7, 14, tzinfo=UTC)),
    )

    class Provider:
        provider_id = "fixture"

        def list_market_caps(self, limit: int):
            assert limit == 2
            return assets

    assert fetch_crypto_market_caps(Provider(), 2) == CryptoMarketCapBatch("fixture", assets)


@pytest.mark.parametrize(
    "response",
    [
        (),
        (CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 2, datetime(2026, 7, 14, tzinfo=UTC)),),
        (
            CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 2, datetime(2026, 7, 14, tzinfo=UTC)),
            CryptoMarketCapAsset("ethereum", "ETH", "Ethereum", 400_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC)),
        ),
    ],
)
def test_crypto_market_cap_provider_contract_fails_closed_for_incomplete_or_malformed_data(response):
    class Provider:
        provider_id = "fixture"

        def list_market_caps(self, limit: int):
            return response

    with pytest.raises(VNextExternalDataError):
        fetch_crypto_market_caps(Provider(), 2)
