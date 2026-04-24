from __future__ import annotations

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.preflight import run_preflight


def test_preflight_warns_in_paper_mode(monkeypatch, tmp_path):
    from stonks_cli.polymarket import guards, lifecycle, preflight, storage

    monkeypatch.setattr(preflight, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(storage, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(guards, "default_state_dir", lambda: tmp_path)

    result = run_preflight(AppConfig(polymarket=PolymarketConfig(enabled=True, paper=True)))

    assert result["overall"] in {"pass", "warn"}
    assert any(check["name"] == "mode" and check["status"] == "warn" for check in result["checks"])


def test_preflight_fails_live_without_private_key(monkeypatch, tmp_path):
    from stonks_cli.polymarket import guards, lifecycle, preflight, storage

    monkeypatch.setattr(preflight, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(storage, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(guards, "default_state_dir", lambda: tmp_path)

    result = run_preflight(AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False)))

    assert result["overall"] == "fail"
    assert any(check["name"] == "private_key" and check["status"] == "fail" for check in result["checks"])
