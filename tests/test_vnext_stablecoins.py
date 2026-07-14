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


def test_stablecoin_classifier_preserves_ranked_batch_order_and_uses_the_supplied_provider_ids():
    bitcoin = CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 20_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC))
    test_dollar = CryptoMarketCapAsset("test-dollar", "TUSD", "Test Dollar", 100_000_000.0, 5_000_000.0, 2, datetime(2026, 7, 14, tzinfo=UTC))
    tether_lookalike = CryptoMarketCapAsset("unverified-tether", "USTX", "Tether Lookalike", 10_000_000.0, 1_000_000.0, 3, datetime(2026, 7, 14, tzinfo=UTC))

    classifications = classify_stablecoins(
        CryptoMarketCapBatch("fixture", (bitcoin, test_dollar, tether_lookalike)), StablecoinClassifier(frozenset({"test-dollar"}))
    )

    assert [(item.asset.provider_asset_id, item.status) for item in classifications] == [
        ("bitcoin", StablecoinStatus.UNCLASSIFIED),
        ("test-dollar", StablecoinStatus.STABLECOIN),
        ("unverified-tether", StablecoinStatus.UNCLASSIFIED),
    ]


def test_stablecoin_classifier_rejects_malformed_inputs_without_guessing():
    batch = CryptoMarketCapBatch(
        "fixture", (CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 20_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC)),)
    )
    with pytest.raises((TypeError, ValueError)):
        StablecoinClassifier(frozenset())
    with pytest.raises(TypeError):
        classify_stablecoins("not-a-batch")
    with pytest.raises(TypeError):
        classify_stablecoins(batch, "not-a-classifier")
