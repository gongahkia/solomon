from __future__ import annotations

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.heartbeat import (
    has_heartbeat_method,
    load_heartbeat_state,
    maybe_send_heartbeat,
)


def test_maybe_send_heartbeat_persists_state(monkeypatch, tmp_path):
    from stonks_cli.polymarket import heartbeat

    monkeypatch.setattr(heartbeat, "default_state_dir", lambda: tmp_path)

    class _Client:
        def __init__(self):
            self.calls: list[str] = []

        def post_heartbeat(self, *, heartbeat_id):
            self.calls.append(heartbeat_id)
            return {"heartbeat_id": "hb-1"}

    client = _Client()
    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False))

    result = maybe_send_heartbeat(cfg, force=True, client=client)

    assert result is not None
    assert result["heartbeat_id"] == "hb-1"
    assert client.calls == [""]
    assert load_heartbeat_state().heartbeat_id == "hb-1"


def test_maybe_send_heartbeat_skips_when_recent(monkeypatch, tmp_path):
    from stonks_cli.polymarket import heartbeat

    monkeypatch.setattr(heartbeat, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(
        heartbeat,
        "load_heartbeat_state",
        lambda: heartbeat.HeartbeatState(heartbeat_id="hb-1", last_sent_at=heartbeat.utc_now_iso()),
    )

    class _Client:
        def post_heartbeat(self, *, heartbeat_id):
            raise AssertionError("heartbeat should have been skipped")

    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False, live_heartbeat_interval_seconds=30))

    assert maybe_send_heartbeat(cfg, client=_Client()) is None


def test_has_heartbeat_method_detects_supported_names():
    class _Client:
        def heartbeat(self, *, heartbeat_id):
            return {"heartbeat_id": heartbeat_id}

    assert has_heartbeat_method(_Client()) is True
