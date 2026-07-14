from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch
from stonks_cli.vnext.crypto_metadata import (
    CryptoAssetMetadata,
    CryptoAssetPlatform,
    ingest_crypto_asset_metadata,
)
from stonks_cli.vnext.errors import VNextExternalDataError


def test_crypto_metadata_ingestion_returns_complete_provider_matched_records_in_batch_order():
    batch = _batch()
    bitcoin = CryptoAssetMetadata("bitcoin", ("layer-1",), (), datetime(2026, 7, 14, tzinfo=UTC))
    ethereum = CryptoAssetMetadata(
        "ethereum",
        ("layer-1", "smart-contract-platform"),
        (CryptoAssetPlatform("ethereum", None),),
        datetime(2026, 7, 14, tzinfo=UTC),
    )

    class Provider:
        provider_id = "fixture"

        def list_asset_metadata(self, provider_asset_ids):
            assert provider_asset_ids == ("bitcoin", "ethereum")
            return (ethereum, bitcoin)

    assert ingest_crypto_asset_metadata(batch, Provider()) == (bitcoin, ethereum)


def test_crypto_metadata_ingestion_fails_closed_for_incomplete_or_malformed_responses():
    class Provider:
        provider_id = "fixture"

        def list_asset_metadata(self, provider_asset_ids):
            return (CryptoAssetMetadata("bitcoin", (), (), datetime(2026, 7, 14, tzinfo=UTC)),)

    with pytest.raises(VNextExternalDataError):
        ingest_crypto_asset_metadata(_batch(), Provider())
    with pytest.raises(ValueError):
        CryptoAssetMetadata("bitcoin", ("z", "a"), (), datetime(2026, 7, 14, tzinfo=UTC))


def _batch() -> CryptoMarketCapBatch:
    return CryptoMarketCapBatch(
        "fixture",
        (
            CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 50_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC)),
            CryptoMarketCapAsset("ethereum", "ETH", "Ethereum", 400_000_000_000.0, 20_000_000_000.0, 2, datetime(2026, 7, 14, tzinfo=UTC)),
        ),
    )
