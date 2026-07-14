from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch
from stonks_cli.vnext.crypto_universe_history import (
    CryptoUniverseHistory,
    append_crypto_universe_history,
    load_crypto_universe_history,
)
from stonks_cli.vnext.crypto_universe_snapshot import CryptoUniverseSnapshot


def test_crypto_universe_history_appends_and_round_trips_private_snapshots(tmp_path):
    first = _snapshot("00000000-0000-4000-8000-000000000001", datetime(2026, 7, 14, tzinfo=UTC))
    second = _snapshot("00000000-0000-4000-8000-000000000002", datetime(2026, 7, 14, tzinfo=UTC) + timedelta(days=1))
    path = tmp_path / "crypto-universe-history.json"

    assert append_crypto_universe_history(path, first) == CryptoUniverseHistory((first,))
    assert append_crypto_universe_history(path, second) == CryptoUniverseHistory((first, second))
    assert load_crypto_universe_history(path) == CryptoUniverseHistory((first, second))
    assert path.stat().st_mode & 0o777 == 0o600


def test_crypto_universe_history_fails_closed_for_malformed_or_incomparable_snapshots(tmp_path):
    first = _snapshot("00000000-0000-4000-8000-000000000001", datetime(2026, 7, 15, tzinfo=UTC))
    earlier = _snapshot("00000000-0000-4000-8000-000000000002", datetime(2026, 7, 14, tzinfo=UTC))
    path = tmp_path / "crypto-universe-history.json"
    append_crypto_universe_history(path, first)

    with pytest.raises(ValueError, match="chronological"):
        append_crypto_universe_history(path, earlier)
    different_provider = _snapshot("00000000-0000-4000-8000-000000000003", datetime(2026, 7, 16, tzinfo=UTC), provider_id="other")
    with pytest.raises(ValueError, match="one provider"):
        append_crypto_universe_history(path, different_provider)
    malformed = tmp_path / "malformed-history.json"
    malformed.write_text("{}", encoding="utf-8")
    malformed.chmod(0o600)
    with pytest.raises(ValueError, match="cannot be loaded"):
        load_crypto_universe_history(malformed)


def _snapshot(snapshot_id: str, captured_at: datetime, *, provider_id: str = "fixture") -> CryptoUniverseSnapshot:
    return CryptoUniverseSnapshot(
        UUID(snapshot_id),
        captured_at,
        CryptoMarketCapBatch(
            provider_id,
            (CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 50_000_000_000.0, 1, captured_at),),
        ),
    )
