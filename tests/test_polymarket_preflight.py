from __future__ import annotations

import types

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


def test_preflight_checks_rust_and_live_arm_when_enabled(monkeypatch, tmp_path):
    from stonks_cli.polymarket import guards, lifecycle, preflight, storage

    monkeypatch.setattr(preflight, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(storage, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(guards, "default_state_dir", lambda: tmp_path)
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "test-key")
    monkeypatch.setenv("STONKS_CLI_POLYMARKET_LIVE_ARMED", "1")
    monkeypatch.setattr(preflight, "_dependency_check", lambda name, module: preflight.PreflightCheck(name=name, status="pass", detail="ok"))
    monkeypatch.setattr(preflight, "_rust_checks", lambda cfg: [preflight.PreflightCheck(name="rust_binary", status="pass", detail="ok")])
    monkeypatch.setattr(preflight, "rust_session", lambda cfg: types.SimpleNamespace(status=lambda: {"message": "ok"}))
    monkeypatch.setattr(
        preflight,
        "authenticated_clob_client",
        lambda cfg: (
            types.SimpleNamespace(
                cancel_order=lambda **kwargs: {},
                get_open_orders=lambda: [],
                post_heartbeat=lambda **kwargs: {"heartbeat_id": "hb-1"},
            ),
            types.SimpleNamespace(api_key="abcd1234"),
        ),
    )

    result = run_preflight(
        AppConfig(
            polymarket=PolymarketConfig(
                enabled=True,
                paper=False,
                rust_hotpath_enabled=True,
            )
        ),
        deep_auth=True,
    )

    assert result["overall"] == "pass"
    assert any(check["name"] == "live_arm" and check["status"] == "pass" for check in result["checks"])
    assert any(check["name"] == "rust_hotpath_session" and check["status"] == "pass" for check in result["checks"])
    assert any(check["name"] == "open_orders_method" and check["status"] == "pass" for check in result["checks"])
    assert any(check["name"] == "heartbeat_method" and check["status"] == "pass" for check in result["checks"])
