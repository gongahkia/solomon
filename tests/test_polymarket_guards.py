from __future__ import annotations

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.guards import (
    active_halt_reason,
    evaluate_trade_guards,
    halt_trading,
    load_guard_state,
    resume_trading,
)
from stonks_cli.polymarket.lifecycle import LiveOrderManager, build_live_order_request
from stonks_cli.polymarket.models import LiveMarketSnapshot, PaperAccount, PaperPosition, TradeProposal
from stonks_cli.polymarket.execution import ExecutionOrder


def _proposal() -> TradeProposal:
    return TradeProposal(
        token_id="YES1",
        market_id="1",
        slug="btc-higher",
        outcome="YES",
        side="BUY",
        price=0.6,
        shares=10,
        notional=6.0,
        score=12.0,
    )


def test_guard_respects_manual_halt(monkeypatch, tmp_path):
    from stonks_cli.polymarket import guards

    monkeypatch.setattr(guards, "default_state_dir", lambda: tmp_path)

    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=True))
    halt_trading(reason="operator_stop")

    reasons = evaluate_trade_guards(cfg, PaperAccount(cash=100.0, realized_pnl=0.0, positions=[], trades=[]), _proposal())

    assert reasons == ["halted:operator_stop"]
    assert active_halt_reason(load_guard_state()) == "operator_stop"
    resume_trading()


def test_guard_blocks_max_daily_loss(monkeypatch, tmp_path):
    from stonks_cli.polymarket import guards

    monkeypatch.setattr(guards, "default_state_dir", lambda: tmp_path)

    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=True, max_daily_loss=10.0))
    account = PaperAccount(cash=100.0, realized_pnl=-11.0, positions=[], trades=[])

    reasons = evaluate_trade_guards(cfg, account, _proposal())

    assert "max_daily_loss_reached" in reasons


def test_guard_blocks_max_live_open_orders(monkeypatch, tmp_path):
    from stonks_cli.polymarket import guards, lifecycle

    monkeypatch.setattr(guards, "default_state_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "default_state_dir", lambda: tmp_path)

    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=False, max_live_open_orders=1))
    manager = LiveOrderManager(cfg)
    manager.register_submitted(
        "order-1",
        build_live_order_request(
            cfg,
            ExecutionOrder(
                token_id="YES1",
                market_id="1",
                slug="btc-higher",
                outcome="YES",
                side="BUY",
                price=0.58,
                shares=12,
            ),
            LiveMarketSnapshot(token_id="YES1", best_bid=0.57, best_ask=0.60, tick_size=0.01),
        ),
    )

    reasons = evaluate_trade_guards(cfg, PaperAccount(cash=100.0, realized_pnl=0.0, positions=[], trades=[]), _proposal())

    assert "max_live_open_orders_reached" in reasons


def test_guard_blocks_max_market_notional(monkeypatch, tmp_path):
    from stonks_cli.polymarket import guards

    monkeypatch.setattr(guards, "default_state_dir", lambda: tmp_path)

    cfg = AppConfig(polymarket=PolymarketConfig(enabled=True, paper=True, max_market_notional=10.0))
    account = PaperAccount(
        cash=100.0,
        realized_pnl=0.0,
        positions=[PaperPosition("YES1", "1", "btc-higher", "YES", 10, 0.6, "2026-01-01T00:00:00Z")],
        trades=[],
    )

    reasons = evaluate_trade_guards(cfg, account, _proposal())

    assert "max_market_notional_reached" in reasons
