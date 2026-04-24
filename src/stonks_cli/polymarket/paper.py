from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from stonks_cli.logging_utils import log_suppressed_exception
from stonks_cli.paths import default_state_dir
from stonks_cli.polymarket.client import utc_now_iso
from stonks_cli.polymarket.models import PaperAccount, PaperPosition, PaperTrade


def _paper_path() -> Path:
    return default_state_dir() / "polymarket_paper.json"


def load_paper_account() -> PaperAccount:
    path = _paper_path()
    if not path.exists():
        raise FileNotFoundError("Polymarket paper account not initialized. Run `stonks-cli polymarket paper init`.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log_suppressed_exception(context="polymarket.paper.load", error=e, path=path)
        raise ValueError("Invalid Polymarket paper account state.")
    return PaperAccount(
        cash=float(payload.get("cash") or 0.0),
        realized_pnl=float(payload.get("realized_pnl") or 0.0),
        positions=[
            PaperPosition(
                token_id=str(item.get("token_id") or ""),
                market_id=str(item.get("market_id") or ""),
                slug=item.get("slug"),
                outcome=item.get("outcome"),
                shares=float(item.get("shares") or 0.0),
                avg_price=float(item.get("avg_price") or 0.0),
                opened_at=str(item.get("opened_at") or ""),
            )
            for item in (payload.get("positions") or [])
            if isinstance(item, dict)
        ],
        trades=[
            PaperTrade(
                ts=str(item.get("ts") or ""),
                action=str(item.get("action") or ""),
                token_id=str(item.get("token_id") or ""),
                market_id=str(item.get("market_id") or ""),
                slug=item.get("slug"),
                outcome=item.get("outcome"),
                shares=float(item.get("shares") or 0.0),
                price=float(item.get("price") or 0.0),
                notional=float(item.get("notional") or 0.0),
                realized_pnl=float(item["realized_pnl"]) if item.get("realized_pnl") is not None else None,
            )
            for item in (payload.get("trades") or [])
            if isinstance(item, dict)
        ],
    )


def save_paper_account(account: PaperAccount) -> None:
    path = _paper_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(account), indent=2), encoding="utf-8")


def init_paper_account(starting_cash: float) -> PaperAccount:
    account = PaperAccount(cash=starting_cash, realized_pnl=0.0, positions=[], trades=[])
    save_paper_account(account)
    return account


def _find_position(account: PaperAccount, token_id: str) -> PaperPosition | None:
    for position in account.positions:
        if position.token_id == token_id:
            return position
    return None


def paper_buy(
    *,
    token_id: str,
    market_id: str,
    slug: str | None,
    outcome: str | None,
    shares: float,
    price: float,
) -> dict[str, object]:
    if shares <= 0 or price <= 0:
        raise ValueError("shares and price must be positive")
    account = load_paper_account()
    notional = shares * price
    if account.cash < notional:
        raise ValueError(f"Insufficient paper cash. Need ${notional:.2f}, have ${account.cash:.2f}")

    positions = list(account.positions)
    trades = list(account.trades)
    position = _find_position(account, token_id)
    if position is None:
        positions.append(
            PaperPosition(
                token_id=token_id,
                market_id=market_id,
                slug=slug,
                outcome=outcome,
                shares=shares,
                avg_price=price,
                opened_at=utc_now_iso(),
            )
        )
    else:
        new_shares = position.shares + shares
        new_avg = ((position.avg_price * position.shares) + notional) / new_shares
        positions = [p for p in positions if p.token_id != token_id]
        positions.append(
            PaperPosition(
                token_id=token_id,
                market_id=position.market_id,
                slug=position.slug,
                outcome=position.outcome,
                shares=new_shares,
                avg_price=round(new_avg, 8),
                opened_at=position.opened_at,
            )
        )

    trades.append(
        PaperTrade(
            ts=utc_now_iso(),
            action="BUY",
            token_id=token_id,
            market_id=market_id,
            slug=slug,
            outcome=outcome,
            shares=shares,
            price=price,
            notional=notional,
        )
    )
    updated = PaperAccount(
        cash=round(account.cash - notional, 8),
        realized_pnl=account.realized_pnl,
        positions=positions,
        trades=trades,
    )
    save_paper_account(updated)
    return {
        "action": "BUY",
        "token_id": token_id,
        "shares": shares,
        "price": price,
        "notional": round(notional, 8),
        "cash": updated.cash,
    }


def paper_sell(*, token_id: str, shares: float, price: float) -> dict[str, object]:
    if shares <= 0 or price <= 0:
        raise ValueError("shares and price must be positive")
    account = load_paper_account()
    position = _find_position(account, token_id)
    if position is None or position.shares < shares:
        raise ValueError("Insufficient paper position to sell")

    notional = shares * price
    realized = (price - position.avg_price) * shares
    remaining = round(position.shares - shares, 8)

    positions = [p for p in account.positions if p.token_id != token_id]
    if remaining > 0:
        positions.append(
            PaperPosition(
                token_id=position.token_id,
                market_id=position.market_id,
                slug=position.slug,
                outcome=position.outcome,
                shares=remaining,
                avg_price=position.avg_price,
                opened_at=position.opened_at,
            )
        )

    trades = list(account.trades)
    trades.append(
        PaperTrade(
            ts=utc_now_iso(),
            action="SELL",
            token_id=token_id,
            market_id=position.market_id,
            slug=position.slug,
            outcome=position.outcome,
            shares=shares,
            price=price,
            notional=notional,
            realized_pnl=round(realized, 8),
        )
    )
    updated = PaperAccount(
        cash=round(account.cash + notional, 8),
        realized_pnl=round(account.realized_pnl + realized, 8),
        positions=positions,
        trades=trades,
    )
    save_paper_account(updated)
    return {
        "action": "SELL",
        "token_id": token_id,
        "shares": shares,
        "price": price,
        "notional": round(notional, 8),
        "realized_pnl": round(realized, 8),
        "cash": updated.cash,
    }


def paper_status(midpoints: dict[str, float] | None = None) -> dict[str, object]:
    account = load_paper_account()
    prices = midpoints or {}
    unrealized = 0.0
    positions = []
    for position in account.positions:
        mark = prices.get(position.token_id, position.avg_price)
        u = (mark - position.avg_price) * position.shares
        unrealized += u
        positions.append(
            {
                **asdict(position),
                "mark_price": mark,
                "market_value": round(mark * position.shares, 8),
                "unrealized_pnl": round(u, 8),
            }
        )

    equity = round(account.cash + sum(p["market_value"] for p in positions), 8)
    return {
        "cash": account.cash,
        "realized_pnl": account.realized_pnl,
        "unrealized_pnl": round(unrealized, 8),
        "equity": equity,
        "positions": positions,
        "trades": [asdict(t) for t in account.trades[-20:]],
    }
