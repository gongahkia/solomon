from __future__ import annotations

from stonks_cli.polymarket.paper import init_paper_account, load_paper_account, paper_buy
from stonks_cli.polymarket.settlement import paper_settle_market


def test_paper_settle_market_realizes_winner_and_loser(monkeypatch, tmp_path):
    from stonks_cli.polymarket import paper

    monkeypatch.setattr(paper, "default_state_dir", lambda: tmp_path)

    init_paper_account(1000.0)
    paper_buy(token_id="YES1", market_id="1", slug="btc-higher", outcome="YES", shares=10, price=0.60)
    paper_buy(token_id="NO1", market_id="1", slug="btc-higher", outcome="NO", shares=5, price=0.30)

    result = paper_settle_market(market_id="1", winning_token_id="YES1")
    account = load_paper_account()

    assert len(result["settled"]) == 2
    assert account.positions == []
    assert account.cash == 1002.5
    assert account.realized_pnl == 2.5
