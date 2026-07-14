from __future__ import annotations

import json

import pytest

from stonks_cli.config import (
    CONFIG_SCHEMA_VERSION,
    REDACTED_CONFIG_VALUE,
    AppConfig,
    load_config,
    migrate_config_data,
    redacted_config_data,
    redacted_config_json,
    save_config,
    validate_config_semantics,
)


def test_load_config_defaults_when_missing(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    cfg = load_config()
    assert cfg.tickers
    assert cfg.schedule.cron


def test_load_config_validates_cron(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    cfg_path.write_text(
        json.dumps(
            {
                "tickers": ["AAPL"],
                "schedule": {"cron": "not a cron"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(Exception):
        load_config()


def test_load_config_normalizes_tickers(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    cfg_path.write_text(
        json.dumps(
            {
                "tickers": ["aapl"],
                "ticker_overrides": {"msft": {"data": {"provider": "stooq"}}},
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config()
    assert cfg.tickers == ["aapl"]  # no normalization after equity removal
    assert "msft" in cfg.ticker_overrides


def test_polymarket_live_min_order_notional_is_preserved(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))
    cfg_path.write_text(
        json.dumps({"polymarket": {"live_min_order_notional_usd": 7.5}}),
        encoding="utf-8",
    )

    cfg = load_config()

    assert cfg.polymarket.live_min_order_notional_usd == 7.5
    assert cfg.polymarket.model_dump(mode="json")["live_min_order_notional_usd"] == 7.5


def test_config_accepts_akshare_provider(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))
    cfg_path.write_text(json.dumps({"data": {"provider": "akshare"}}), encoding="utf-8")

    assert load_config().data.provider == "akshare"


def test_carrymirror_defaults_keep_live_disabled(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    cfg = load_config()

    assert cfg.carrymirror.paper is True
    assert cfg.carrymirror.live_armed is False
    assert cfg.carrymirror.live_armed_env == "STONKS_CLI_CARRY_LIVE_ARMED"
    assert cfg.carrymirror.live_secrets_path == "~/.config/stonks-cli/carry-live.env"
    assert cfg.carrymirror.tiny_live_min_usd == 50.0
    assert cfg.carrymirror.tiny_live_max_usd == 200.0
    assert cfg.carrymirror.max_total_live_usd == 0.0
    assert cfg.carrymirror.min_net_apr == 0.15
    assert cfg.carrymirror.alert_sink == "disabled"
    assert set(cfg.carrymirror.alert_events) == {"kill_switch", "ledger_mismatch", "service_restart", "stale_data"}
    assert "bybit" in cfg.legal_policy.blocked_venue_ids
    assert "whalemirror_live_target_selection" in cfg.legal_policy.blocked_strategy_classes


def test_legacy_config_migrates_to_current_schema(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"tickers": ["aapl"]}), encoding="utf-8")
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    cfg = load_config()

    assert cfg.schema_version == 2
    assert cfg.tickers == ["aapl"]


def test_explicit_v1_config_migrates_without_mutating_input():
    legacy = {"schema_version": 1, "vnext": {"moomoo": {"host": "127.0.0.1"}}}

    migrated = migrate_config_data(legacy)

    assert legacy["schema_version"] == 1
    assert migrated["schema_version"] == CONFIG_SCHEMA_VERSION
    assert AppConfig.model_validate(migrated).vnext.moomoo.read_only is True


def test_config_schema_discriminator_is_serialized_and_rejects_legacy_value():
    cfg = AppConfig()

    assert cfg.schema_version == CONFIG_SCHEMA_VERSION
    assert cfg.model_dump(mode="json")["schema_version"] == CONFIG_SCHEMA_VERSION
    with pytest.raises(ValueError):
        AppConfig.model_validate({"schema_version": 1})


def test_vnext_feature_flags_are_explicit_opt_in_with_execution_disabled():
    flags = AppConfig().vnext.features

    assert flags.model_dump() == {
        "broker_data": False,
        "crypto_research": False,
        "portfolio": False,
        "operator_reports": False,
        "execution": False,
    }
    with pytest.raises(ValueError):
        AppConfig.model_validate({"vnext": {"features": {"broker_data": "true"}}})
    with pytest.raises(ValueError):
        AppConfig.model_validate({"vnext": {"features": {"execution": True}}})
    with pytest.raises(ValueError):
        AppConfig.model_validate({"vnext": {"features": {"unknown": True}}})


def test_semantic_config_validator_accepts_consistent_vnext_activation():
    cfg = AppConfig.model_validate(
        {
            "vnext": {
                "enabled": True,
                "moomoo": {"enabled": True},
                "research": {"enabled": True},
                "operator": {"telegram": {"enabled": True}},
                "features": {"broker_data": True, "crypto_research": True, "operator_reports": True},
            }
        }
    )

    validate_config_semantics(cfg)


@pytest.mark.parametrize(
    ("vnext", "message"),
    [
        ({"features": {"broker_data": True}}, "vnext.enabled must be true"),
        ({"enabled": True, "moomoo": {"enabled": True}}, "vnext.moomoo.enabled requires"),
        ({"enabled": True, "research": {"enabled": True}}, "vnext.research.enabled requires"),
        ({"enabled": True, "operator": {"telegram": {"enabled": True}}}, "vnext.operator.telegram.enabled requires"),
    ],
)
def test_semantic_config_validator_rejects_inconsistent_vnext_activation(vnext, message):
    with pytest.raises(ValueError, match=message):
        validate_config_semantics(AppConfig.model_validate({"vnext": vnext}))


def test_load_config_fails_closed_for_invalid_semantics(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"vnext": {"features": {"broker_data": True}}}), encoding="utf-8")
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    with pytest.raises(ValueError, match="invalid config semantics"):
        load_config()


@pytest.mark.parametrize("data", [[], {"schema_version": True}, {"schema_version": "2"}])
def test_malformed_config_version_fails_closed(data):
    with pytest.raises(ValueError, match="config root must be an object|schema_version must be an integer"):
        migrate_config_data(data)


def test_future_config_schema_is_rejected(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"schema_version": 3}), encoding="utf-8")
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    with pytest.raises(ValueError, match="unsupported future schema_version:3"):
        load_config()


def test_vnext_defaults_fail_closed():
    cfg = AppConfig()

    assert cfg.vnext.enabled is False
    assert cfg.vnext.moomoo.enabled is False
    assert cfg.vnext.moomoo.read_only is True
    assert cfg.vnext.operator.execution_mode == "disabled"
    assert cfg.vnext.operator.broker_app_only is True


def test_redacted_config_hides_sensitive_values():
    cfg = AppConfig(api_keys={"alpaca_api_key": "exposed", "alpaca_secret_key": "also-exposed"})
    data = redacted_config_data(cfg)

    assert data["api_keys"] == "***REDACTED***"
    assert data["carrymirror"]["telegram_bot_token_env"] == "***REDACTED***"


def test_redacted_config_hides_nested_authentication_and_webhook_values():
    secrets = {"authorization": "Bearer bearer-secret", "cookie": "session-secret", "webhook": "webhook-secret"}
    cfg = AppConfig(
        webhook_url="https://example.test/hook?token=webhook-secret",
        strategy_params={"headers": secrets},
    )

    rendered = redacted_config_json(cfg)

    assert REDACTED_CONFIG_VALUE in rendered
    assert all(secret not in rendered for secret in secrets.values())
    assert "https://example.test/hook" not in rendered


def test_save_config_uses_owner_only_permissions(tmp_path):
    path = tmp_path / "config.json"
    save_config(AppConfig(), path)

    assert path.stat().st_mode & 0o777 == 0o600
