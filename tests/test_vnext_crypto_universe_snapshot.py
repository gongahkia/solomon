import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch
from stonks_cli.vnext.crypto_universe_snapshot import (
    CryptoUniverseSnapshot,
    create_crypto_universe_snapshot,
    load_crypto_universe_snapshot,
    save_crypto_universe_snapshot,
)
from stonks_cli.vnext.foundation import FrozenUTCClock


def test_crypto_universe_snapshot_persists_private_immutable_batch(tmp_path):
    snapshot = create_crypto_universe_snapshot(
        CryptoMarketCapBatch(
            "fixture",
            (CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC)),),
        ),
        FrozenUTCClock(datetime(2026, 7, 14, 1, 2, 3, tzinfo=UTC)),
        snapshot_id=UUID("00000000-0000-4000-8000-000000000001"),
    )

    path = save_crypto_universe_snapshot(tmp_path, snapshot)

    assert path.stat().st_mode & 0o777 == 0o600
    assert load_crypto_universe_snapshot(path) == snapshot
    with pytest.raises(FileExistsError):
        save_crypto_universe_snapshot(tmp_path, snapshot)


def test_crypto_universe_snapshot_readback_fails_closed_for_malformed_data(tmp_path):
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps({"version": 1, "assets": []}), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(ValueError, match="cannot be loaded"):
        load_crypto_universe_snapshot(path)


def test_crypto_universe_snapshot_requires_absolute_private_storage(tmp_path):
    snapshot = CryptoUniverseSnapshot(
        UUID("00000000-0000-4000-8000-000000000001"),
        datetime(2026, 7, 14, tzinfo=UTC),
        CryptoMarketCapBatch(
            "fixture",
            (CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 2_000_000_000_000.0, 1, datetime(2026, 7, 14, tzinfo=UTC)),),
        ),
    )

    with pytest.raises(ValueError, match="directory must be absolute"):
        save_crypto_universe_snapshot(Path("relative"), snapshot)
