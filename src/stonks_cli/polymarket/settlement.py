from __future__ import annotations

from dataclasses import asdict

from stonks_cli.polymarket.client import utc_now_iso
from stonks_cli.polymarket.paper import load_paper_account, save_paper_account
from stonks_cli.polymarket.models import PaperAccount, PaperTrade


def paper_settle_market(*, market_id: str, winning_token_id: str, reason: str = "market_resolution") -> dict[str, object]:
    account = load_paper_account()
    positions = []
    trades = list(account.trades)
    realized_delta = 0.0
    cash_delta = 0.0
    settled: list[dict[str, object]] = []

    for position in account.positions:
        if position.market_id != market_id:
            positions.append(position)
            continue
        settle_price = 1.0 if position.token_id == winning_token_id else 0.0
        payout = round(position.shares * settle_price, 8)
        realized = round((settle_price - position.avg_price) * position.shares, 8)
        cash_delta += payout
        realized_delta += realized
        trades.append(
            PaperTrade(
                ts=utc_now_iso(),
                action="SETTLE",
                token_id=position.token_id,
                market_id=position.market_id,
                slug=position.slug,
                outcome=position.outcome,
                shares=position.shares,
                price=settle_price,
                notional=payout,
                realized_pnl=realized,
                reason=reason,
            )
        )
        settled.append(
            {
                "token_id": position.token_id,
                "shares": position.shares,
                "settle_price": settle_price,
                "realized_pnl": realized,
                "won": position.token_id == winning_token_id,
            }
        )

    updated = PaperAccount(
        cash=round(account.cash + cash_delta, 8),
        realized_pnl=round(account.realized_pnl + realized_delta, 8),
        positions=positions,
        trades=trades,
    )
    save_paper_account(updated)
    return {
        "market_id": market_id,
        "winning_token_id": winning_token_id,
        "cash_delta": round(cash_delta, 8),
        "realized_pnl_delta": round(realized_delta, 8),
        "settled": settled,
        "account": asdict(updated),
    }
