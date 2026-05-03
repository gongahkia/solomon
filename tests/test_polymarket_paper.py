from __future__ import annotations

from stonks_cli.polymarket.paper import (
    init_paper_account,
    load_paper_account,
    paper_buy,
    paper_sell,
    paper_status,
    pnl_by_signal,
)


def test_polymarket_paper_buy_sell_cycle(monkeypatch, tmp_path):
    from stonks_cli.polymarket import paper

    monkeypatch.setattr(paper, "default_state_dir", lambda: tmp_path)

    init_paper_account(100.0)
    buy = paper_buy(
        token_id="YES1",
        market_id="1",
        slug="market-1",
        outcome="YES",
        shares=100.0,
        price=0.40,
    )
    assert round(buy["cash"], 2) == 60.00

    account = load_paper_account()
    assert len(account.positions) == 1
    assert round(account.positions[0].avg_price, 2) == 0.40

    sell = paper_sell(token_id="YES1", shares=50.0, price=0.60)
    assert round(sell["realized_pnl"], 2) == 10.00
    status = paper_status({"YES1": 0.70})
    assert round(status["cash"], 2) == 90.00
    assert round(status["realized_pnl"], 2) == 10.00
    assert round(status["unrealized_pnl"], 2) == 15.00


def test_pnl_by_signal_attribution(monkeypatch, tmp_path):
    from stonks_cli.polymarket import paper

    monkeypatch.setattr(paper, "default_state_dir", lambda: tmp_path)
    init_paper_account(100.0)
    paper_buy(token_id="A", market_id="m1", slug=None, outcome="YES",
              shares=10.0, price=0.40, reason="score=2.50|wallets=3") # wallet_copy
    paper_buy(token_id="B", market_id="m2", slug=None, outcome="YES",
              shares=10.0, price=0.40, reason="score=1.50|wallets=0") # scanner
    paper_sell(token_id="A", shares=10.0, price=0.60, reason="TARGET_HIT")
    paper_sell(token_id="B", shares=10.0, price=0.30, reason="STOP_LOSS")

    rollup = pnl_by_signal()
    by_sig = {row["signal"]: row for row in rollup["by_signal"]}
    assert round(by_sig["wallet_copy"]["realized_pnl"], 2) == 2.00
    assert round(by_sig["scanner"]["realized_pnl"], 2) == -1.00
    assert by_sig["wallet_copy"]["round_trips"] == 1
    assert by_sig["scanner"]["round_trips"] == 1
    assert round(rollup["total_realized_pnl"], 2) == 1.00
    # tearsheet metrics present
    for sig in ("wallet_copy", "scanner"):
        assert "sortino" in by_sig[sig]
        assert "calmar" in by_sig[sig]
        assert "profit_factor" in by_sig[sig]
        assert "expectancy" in by_sig[sig]
    assert by_sig["wallet_copy"]["avg_win"] > 0
    assert by_sig["scanner"]["avg_loss"] < 0

