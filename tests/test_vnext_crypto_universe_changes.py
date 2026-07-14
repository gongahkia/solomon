from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch
from stonks_cli.vnext.crypto_universe_changes import CryptoUniverseRankChange, detect_crypto_universe_changes
from stonks_cli.vnext.crypto_universe_snapshot import CryptoUniverseSnapshot
from stonks_cli.vnext.errors import VNextInvariantError


def test_crypto_universe_change_detection_reports_membership_and_rank_deltas():
    bitcoin = CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 50_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC))
    bitcoin_after = CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 1_900_000_000_000.0, 45_000_000_000.0, 2, datetime(2026, 7, 15, tzinfo=UTC))
    ethereum = CryptoMarketCapAsset("ethereum", "ETH", "Ethereum", 400_000_000_000.0, 20_000_000_000.0, 2, datetime(2026, 7, 14, tzinfo=UTC))
    solana = CryptoMarketCapAsset("solana", "SOL", "Solana", 100_000_000_000.0, 10_000_000_000.0, 1, datetime(2026, 7, 15, tzinfo=UTC))
    previous = CryptoUniverseSnapshot(
        UUID("00000000-0000-4000-8000-000000000001"),
        datetime(2026, 7, 14, tzinfo=UTC),
        CryptoMarketCapBatch("fixture", (bitcoin, ethereum)),
    )
    current = CryptoUniverseSnapshot(
        UUID("00000000-0000-4000-8000-000000000002"),
        datetime(2026, 7, 14, tzinfo=UTC) + timedelta(days=1),
        CryptoMarketCapBatch("fixture", (solana, bitcoin_after)),
    )

    changes = detect_crypto_universe_changes(previous, current)

    assert changes.added == (solana,)
    assert changes.removed == (ethereum,)
    assert changes.rank_changes == (CryptoUniverseRankChange("bitcoin", 1, 2),)


def test_crypto_universe_change_detection_fails_closed_for_incomparable_snapshots():
    asset = CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 50_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC))
    previous = CryptoUniverseSnapshot(
        UUID("00000000-0000-4000-8000-000000000001"), datetime(2026, 7, 15, tzinfo=UTC), CryptoMarketCapBatch("first", (asset,))
    )
    current = CryptoUniverseSnapshot(
        UUID("00000000-0000-4000-8000-000000000002"), datetime(2026, 7, 14, tzinfo=UTC), CryptoMarketCapBatch("second", (asset,))
    )

    with pytest.raises(VNextInvariantError, match="chronological"):
        detect_crypto_universe_changes(previous, current)
    later_different_provider = CryptoUniverseSnapshot(
        UUID("00000000-0000-4000-8000-000000000003"), datetime(2026, 7, 16, tzinfo=UTC), CryptoMarketCapBatch("second", (asset,))
    )
    with pytest.raises(VNextInvariantError, match="different providers"):
        detect_crypto_universe_changes(previous, later_different_provider)
