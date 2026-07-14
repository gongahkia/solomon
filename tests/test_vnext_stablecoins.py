from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch
from stonks_cli.vnext.stablecoins import StablecoinClassifier, StablecoinStatus, classify_stablecoins


def test_stablecoin_classifier_marks_only_curated_provider_ids_as_stablecoins():
    tether = CryptoMarketCapAsset("tether", "USDT", "Tether", 100_000_000_000.0, 50_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC))
    bitcoin = CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 20_000_000_000.0, 2, datetime(2026, 7, 14, tzinfo=UTC))
    batch = CryptoMarketCapBatch("fixture", (tether, bitcoin))

    classifications = classify_stablecoins(batch)

    assert [(item.asset.symbol, item.status) for item in classifications] == [
        ("USDT", StablecoinStatus.STABLECOIN),
        ("BTC", StablecoinStatus.UNCLASSIFIED),
    ]


def test_stablecoin_classifier_rejects_malformed_inputs_without_guessing():
    with pytest.raises((TypeError, ValueError)):
        StablecoinClassifier(frozenset())
    with pytest.raises(TypeError):
        classify_stablecoins("not-a-batch")
