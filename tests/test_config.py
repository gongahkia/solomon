from __future__ import annotations

import json

import pytest

from stonks_cli.config import load_config


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
    assert cfg.carrymirror.max_total_live_usd == 0.0
    assert cfg.carrymirror.min_net_apr == 0.15
    assert cfg.carrymirror.alert_sink == "disabled"
    assert set(cfg.carrymirror.alert_events) == {"kill_switch", "ledger_mismatch", "service_restart", "stale_data"}
    assert "bybit" in cfg.legal_policy.blocked_venue_ids
    assert "whalemirror_live_target_selection" in cfg.legal_policy.blocked_strategy_classes
