from __future__ import annotations

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.models import PaperAccount, PaperPosition
from stonks_cli.polymarket.risk import (
    build_trade_proposal,
    kelly_fraction_for_binary,
    vol_target_fraction_for_binary,
)


def test_vol_target_higher_for_extreme_prices():
    # at entry=0.5 vol is max => smaller fraction; at extreme price vol shrinks => larger fraction
    f_mid = vol_target_fraction_for_binary(target_per_trade=0.05, entry_price=0.5)
    f_low = vol_target_fraction_for_binary(target_per_trade=0.05, entry_price=0.10)
    assert f_low > f_mid > 0


def test_vol_target_zero_on_invalid_inputs():
    assert vol_target_fraction_for_binary(target_per_trade=0.0, entry_price=0.5) == 0.0
    assert vol_target_fraction_for_binary(target_per_trade=0.05, entry_price=0.0) == 0.0
    assert vol_target_fraction_for_binary(target_per_trade=0.05, entry_price=1.0) == 0.0


def test_kelly_binary_zero_at_parity():
    assert kelly_fraction_for_binary(p_win=0.5, entry_price=0.5) == 0.0


def test_kelly_binary_positive_when_edge():
    f = kelly_fraction_for_binary(p_win=0.6, entry_price=0.5)
    assert round(f, 4) == 0.2


def test_kelly_binary_clamped_to_zero_when_negative_edge():
    assert kelly_fraction_for_binary(p_win=0.4, entry_price=0.5) == 0.0


def test_kelly_binary_invalid_inputs():
    assert kelly_fraction_for_binary(p_win=0.0, entry_price=0.5) == 0.0
    assert kelly_fraction_for_binary(p_win=0.5, entry_price=0.0) == 0.0
    assert kelly_fraction_for_binary(p_win=0.5, entry_price=1.0) == 0.0


class _Scan:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_build_trade_proposal_accepts_strong_scan():
    cfg = AppConfig(
        polymarket=PolymarketConfig(
            auto_trade_enabled=True,
            auto_trade_min_score=5.0,
            auto_trade_min_target_wallets=1,
            max_position_fraction=0.10,
            min_cash_reserve_fraction=0.10,
            max_open_positions=5,
        )
    )
    account = PaperAccount(cash=1000.0, realized_pnl=0.0, positions=[], trades=[])
    scan = _Scan(
        status="PASS",
        token_id="YES1",
        market_id="1",
        slug="market-1",
        outcome="YES",
        midpoint=0.50,
        score=12.0,
        target_wallet_count=2,
    )

    decision = build_trade_proposal(cfg, account, scan)

    assert decision.accepted is True
    assert decision.proposal is not None
    assert round(decision.proposal.notional, 2) == 100.00
    assert round(decision.proposal.target_price or 0, 2) == 0.60
    assert round(decision.proposal.stop_price or 0, 2) == 0.42


def test_build_trade_proposal_rejects_duplicate_position():
    cfg = AppConfig(
        polymarket=PolymarketConfig(
            auto_trade_enabled=True,
            auto_trade_min_score=5.0,
            auto_trade_min_target_wallets=1,
        )
    )
    account = PaperAccount(
        cash=1000.0,
        realized_pnl=0.0,
        positions=[PaperPosition("YES1", "1", "market-1", "YES", 10, 0.4, "2026-01-01T00:00:00Z")],
        trades=[],
    )
    scan = _Scan(
        status="PASS",
        token_id="YES1",
        market_id="1",
        slug="market-1",
        outcome="YES",
        midpoint=0.50,
        score=12.0,
        target_wallet_count=2,
    )

    decision = build_trade_proposal(cfg, account, scan)

    assert decision.accepted is False
    assert "position_already_open" in decision.reasons
