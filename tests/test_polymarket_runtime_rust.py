from __future__ import annotations

import sys
import types

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.stream import MarketStateCache


def _import_commands(monkeypatch):
    blocking = types.ModuleType("apscheduler.schedulers.blocking")
    blocking.BlockingScheduler = object
    background = types.ModuleType("apscheduler.schedulers.background")
    background.BackgroundScheduler = object
    cron = types.ModuleType("apscheduler.triggers.cron")

    class _CronTrigger:
        @classmethod
        def from_crontab(cls, expr):
            return expr

    cron.CronTrigger = _CronTrigger
    monkeypatch.setitem(sys.modules, "apscheduler", types.ModuleType("apscheduler"))
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers", types.ModuleType("apscheduler.schedulers"))
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers.blocking", blocking)
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers.background", background)
    monkeypatch.setitem(sys.modules, "apscheduler.triggers", types.ModuleType("apscheduler.triggers"))
    monkeypatch.setitem(sys.modules, "apscheduler.triggers.cron", cron)

    from stonks_cli import commands

    return commands


def test_runtime_loop_forwards_market_and_user_events_to_rust(monkeypatch):
    commands = _import_commands(monkeypatch)
    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False, rust_hotpath_enabled=True))

    class _Rust:
        def __init__(self):
            self.market_events: list[dict[str, object]] = []
            self.user_events: list[dict[str, object]] = []

        def apply_market_event(self, event):
            self.market_events.append(event)

        def apply_user_event(self, event):
            self.user_events.append(event)
            return []

    rust = _Rust()
    monkeypatch.setattr(commands, "load_config", lambda: cfg)
    monkeypatch.setattr(commands, "_polymarket_client", lambda: object())
    monkeypatch.setattr(commands, "do_polymarket_scan", lambda **kwargs: [{"token_id": "YES1"}])
    monkeypatch.setattr("stonks_cli.polymarket.rust_bridge.rust_session", lambda cfg: rust)
    monkeypatch.setattr(
        "stonks_cli.polymarket.auth.derive_api_credentials",
        lambda cfg: types.SimpleNamespace(as_dict=lambda: {"apiKey": "k", "secret": "s", "passphrase": "p"}),
    )

    async def _market_run_once(self, *, max_messages=None, event_handler=None):
        event = {"event_type": "best_bid_ask", "asset_id": "YES1", "best_bid": "0.41", "best_ask": "0.43"}
        snapshot = self.cache.apply(event)
        if event_handler is not None:
            event_handler(
                event,
                {
                    "token_id": snapshot.token_id,
                    "best_bid": snapshot.best_bid,
                    "best_ask": snapshot.best_ask,
                    "midpoint": snapshot.midpoint,
                    "last_trade_price": snapshot.last_trade_price,
                    "tick_size": snapshot.tick_size,
                    "resolved": snapshot.resolved,
                    "last_event_type": snapshot.last_event_type,
                    "last_event_at": snapshot.last_event_at,
                },
            )
        return []

    async def _user_run_once(self, *, order_manager=None, max_messages=None, event_handler=None):
        event = {
            "event_type": "order",
            "id": "order-1",
            "asset_id": "YES1",
            "market": "m1",
            "side": "BUY",
            "price": "0.42",
            "original_size": "10",
            "size_matched": "4",
            "type": "UPDATE",
        }
        record = order_manager.apply_user_event(event) if order_manager is not None else None
        if event_handler is not None:
            event_handler(event, None if record is None else {"order_id": record.order_id})
        return []

    monkeypatch.setattr("stonks_cli.polymarket.websocket.MarketWebSocketClient.run_once", _market_run_once)
    monkeypatch.setattr("stonks_cli.polymarket.websocket.UserWebSocketClient.run_once", _user_run_once)

    def _run_runtime_loop(client, *, cfg, limit, scan_cfg, cycles, sleep_seconds, stream_hook):
        cache = MarketStateCache()
        stream_hook(iteration=1, market_cache=cache)
        return {"cycles": cycles, "snapshots": list(cache.as_dict())}

    monkeypatch.setattr("stonks_cli.polymarket.runtime.run_runtime_loop", _run_runtime_loop)

    result = commands.do_polymarket_runtime_loop(limit=1, cycles=1, sleep_seconds=0.0, market_messages=1, user_messages=1)

    assert result["cycles"] == 1
    assert result["snapshots"] == ["YES1"]
    assert rust.market_events[0]["event_type"] == "best_bid_ask"
    assert rust.user_events[0]["event_type"] == "order"
