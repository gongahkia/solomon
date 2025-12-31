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

    # Model defaults
    assert cfg.model.backend == "auto"
    assert cfg.model.max_new_tokens >= 1


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
    assert cfg.tickers == ["AAPL.US"]
    assert "MSFT.US" in cfg.ticker_overrides


def test_load_config_accepts_new_llm_backends(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    cfg_path.write_text(
        json.dumps(
            {
                "model": {
                    "backend": "llama_cpp",
                    "path": "~/models/model.gguf",
                    "offline": True,
                }
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config()
    assert cfg.model.backend == "llama_cpp"
    assert cfg.model.offline is True


def test_load_config_rejects_unknown_model_backend(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    cfg_path.write_text(
        json.dumps({"model": {"backend": "not-a-backend"}}),
        encoding="utf-8",
    )

    with pytest.raises(Exception):
        load_config()
