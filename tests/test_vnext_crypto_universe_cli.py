import json
from datetime import UTC, datetime
from uuid import UUID

from typer.testing import CliRunner

from stonks_cli.cli import app
from stonks_cli.errors import ExitCodes
from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch
from stonks_cli.vnext.crypto_universe_snapshot import CryptoUniverseSnapshot, save_crypto_universe_snapshot


def test_crypto_universe_cli_renders_private_persisted_snapshot(tmp_path):
    captured_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    snapshot = CryptoUniverseSnapshot(
        UUID("12345678-1234-5678-1234-567812345678"),
        captured_at,
        CryptoMarketCapBatch("fixture", (CryptoMarketCapAsset("bitcoin", "BTC", "Bitcoin", 1.0, 2.0, 1, captured_at),)),
    )
    path = save_crypto_universe_snapshot(tmp_path, snapshot)

    result = CliRunner().invoke(app, ["vnext", "crypto-universe", "--snapshot", str(path)])

    assert result.exit_code == 0
    assert json.loads(result.output) == snapshot.to_data()


def test_crypto_universe_cli_fails_closed_for_malformed_snapshot(tmp_path):
    path = tmp_path / "crypto-universe.json"
    path.write_text("not-json", encoding="utf-8")
    path.chmod(0o600)

    result = CliRunner().invoke(app, ["vnext", "crypto-universe", "--snapshot", str(path)])

    assert result.exit_code == ExitCodes.USAGE_ERROR
    assert "cannot be loaded" in result.output
