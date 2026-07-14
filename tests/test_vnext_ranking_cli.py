import json

from typer.testing import CliRunner

import stonks_cli.cli as cli
from stonks_cli.cli import app
from stonks_cli.config import AppConfig
from stonks_cli.errors import ExitCodes


def _enabled_config() -> AppConfig:
    return AppConfig.model_validate({"vnext": {"enabled": True, "features": {"crypto_research": True}}})


def _components() -> list[dict[str, object]]:
    return [
        {
            "provider_id": "fixture",
            "provider_asset_id": asset_id,
            "factor_id": factor_id,
            "raw_value": 0.1,
            "normalized_score": score,
        }
        for asset_id, score in (("bitcoin", 0.8), ("ethereum", 0.6))
        for factor_id in ("trend", "momentum", "mean_reversion", "risk_adjusted_performance")
    ]


def test_vnext_ranking_cli_ranks_canonical_local_components_with_configured_weights(tmp_path, monkeypatch):
    path = tmp_path / "components.json"
    path.write_text(json.dumps(_components()), encoding="utf-8")
    monkeypatch.setattr(cli, "load_config", _enabled_config)

    result = CliRunner().invoke(app, ["rank", "--components", str(path)])

    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {"provider_id": "fixture", "provider_asset_id": "bitcoin", "rank": 1, "weighted_score": 0.8},
        {"provider_id": "fixture", "provider_asset_id": "ethereum", "rank": 2, "weighted_score": 0.6},
    ]


def test_vnext_ranking_cli_fails_closed_for_disabled_or_malformed_input(tmp_path, monkeypatch):
    path = tmp_path / "components.json"
    path.write_text("[]", encoding="utf-8")

    result = CliRunner().invoke(app, ["rank", "--components", str(path)])

    assert result.exit_code == ExitCodes.BAD_CONFIG
    assert "not enabled" in result.output
    monkeypatch.setattr(cli, "load_config", _enabled_config)
    result = CliRunner().invoke(app, ["rank", "--components", str(path)])
    assert result.exit_code == ExitCodes.USAGE_ERROR
    assert "components are invalid" in result.output
