from __future__ import annotations

from stonks_cli.polymarket.paper import init_paper_account, load_paper_account, paper_buy, paper_sell, paper_status


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

