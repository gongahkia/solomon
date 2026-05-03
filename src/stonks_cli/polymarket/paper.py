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
                target_price=float(item["target_price"]) if item.get("target_price") is not None else None,
                stop_price=float(item["stop_price"]) if item.get("stop_price") is not None else None,
                thesis=item.get("thesis"),
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
                reason=item.get("reason"),
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
    target_price: float | None = None,
    stop_price: float | None = None,
    thesis: str | None = None,
    reason: str | None = None,
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
                target_price=target_price,
                stop_price=stop_price,
                thesis=thesis,
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
                target_price=position.target_price if target_price is None else target_price,
                stop_price=position.stop_price if stop_price is None else stop_price,
                thesis=position.thesis if thesis is None else thesis,
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
            reason=reason,
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


def paper_sell(*, token_id: str, shares: float, price: float, reason: str | None = None) -> dict[str, object]:
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
                target_price=position.target_price,
                stop_price=position.stop_price,
                thesis=position.thesis,
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
            reason=reason,
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


def _classify_signal(reason: str | None) -> str:
    if not reason:
        return "manual" # no reason = cli paper buy
    text = str(reason).lower()
    if "wallets=" in text:
        try:
            after = text.split("wallets=", 1)[1]
            n = int("".join(ch for ch in after if ch.isdigit()) or "0")
            if n > 0:
                return "wallet_copy"
        except Exception:
            pass
    if "score=" in text:
        return "scanner" # structural score only, no wallet vote
    if text in {"target_hit", "stop_loss", "stale_position"}:
        return "exit" # sell-side exit reason; bucket by buy reason via fifo
    return "other"


def _sharpe_and_drawdown(returns: list[float]) -> tuple[float, float]:
    """Return (sharpe, max_drawdown_pct) from a list of per-trade returns.
    sharpe is unannualized (per-trade); max DD on cumulative compounded equity."""
    if not returns:
        return 0.0, 0.0
    n = len(returns)
    mean = sum(returns) / n
    if n > 1:
        var = sum((r - mean) ** 2 for r in returns) / (n - 1)
        std = var ** 0.5
    else:
        std = 0.0
    sharpe = (mean / std) if std > 1e-12 else 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= (1.0 + r)
        peak = max(peak, equity)
        if peak > 0:
            dd = (equity - peak) / peak
            if dd < max_dd:
                max_dd = dd
    return round(sharpe, 4), round(max_dd, 4)


def _tearsheet_metrics(returns: list[float], pnls: list[float]) -> dict[str, float]:
    """Quantstats-style metrics: sortino, calmar, profit_factor, expectancy."""
    sharpe, max_dd = _sharpe_and_drawdown(returns)
    n = len(returns)
    if n == 0:
        return {"sharpe": 0.0, "sortino": 0.0, "calmar": 0.0, "max_drawdown": 0.0,
                "profit_factor": 0.0, "expectancy": 0.0, "avg_win": 0.0, "avg_loss": 0.0}
    mean_ret = sum(returns) / n
    downside = [r for r in returns if r < 0]
    if downside:
        d_var = sum(r * r for r in downside) / len(downside) # semi-deviation
        d_std = d_var ** 0.5
        sortino = (mean_ret / d_std) if d_std > 1e-12 else 0.0
    else:
        sortino = float("inf") if mean_ret > 0 else 0.0
    calmar = (mean_ret / abs(max_dd)) if max_dd < -1e-12 else 0.0
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 1e-12 else (float("inf") if gross_win > 0 else 0.0)
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (-gross_loss / len(losses)) if losses else 0.0
    win_rate = len(wins) / n
    expectancy = win_rate * avg_win + (1.0 - win_rate) * avg_loss
    def _safe(x: float) -> float:
        return round(x, 4) if x not in (float("inf"), float("-inf")) else 0.0
    return {
        "sharpe": sharpe,
        "sortino": _safe(sortino),
        "calmar": _safe(calmar),
        "max_drawdown": max_dd,
        "profit_factor": _safe(profit_factor),
        "expectancy": round(expectancy, 6),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
    }


def pnl_by_signal() -> dict[str, object]:
    """FIFO-match buys to sells per token, attribute realized pnl to the buy's signal."""
    from collections import defaultdict, deque

    account = load_paper_account()
    trades = sorted(account.trades, key=lambda t: t.ts)
    open_lots: dict[str, deque] = defaultdict(deque) # token_id -> deque[(qty, price, signal)]
    realized: dict[str, dict[str, float]] = defaultdict(lambda: {"realized_pnl": 0.0, "round_trips": 0, "wins": 0, "buy_notional": 0.0, "sell_notional": 0.0})
    returns_by_sig: dict[str, list[float]] = defaultdict(list)
    pnls_by_sig: dict[str, list[float]] = defaultdict(list)

    for tr in trades:
        if tr.action.upper() == "BUY":
            sig = _classify_signal(tr.reason)
            open_lots[tr.token_id].append((tr.shares, tr.price, sig))
            realized[sig]["buy_notional"] += tr.notional
        elif tr.action.upper() == "SELL":
            remaining = tr.shares
            lots = open_lots[tr.token_id]
            while remaining > 1e-12 and lots:
                lot_qty, lot_price, lot_sig = lots[0]
                matched = min(remaining, lot_qty)
                pnl = (tr.price - lot_price) * matched
                bucket = realized[lot_sig]
                bucket["realized_pnl"] += pnl
                bucket["round_trips"] += 1
                bucket["sell_notional"] += matched * tr.price
                if pnl > 0:
                    bucket["wins"] += 1
                cost = lot_price * matched
                if cost > 0:
                    returns_by_sig[lot_sig].append(pnl / cost)
                pnls_by_sig[lot_sig].append(pnl)
                remaining -= matched
                if matched >= lot_qty - 1e-12:
                    lots.popleft()
                else:
                    lots[0] = (lot_qty - matched, lot_price, lot_sig)
            if remaining > 1e-9:
                bucket = realized["unknown_sell"]
                bucket["realized_pnl"] += (tr.price * remaining) - 0.0
                bucket["round_trips"] += 1
                bucket["sell_notional"] += tr.price * remaining

    # open exposure per signal from remaining lots
    open_exposure: dict[str, float] = defaultdict(float)
    open_shares: dict[str, float] = defaultdict(float)
    for token_id, lots in open_lots.items():
        for qty, price, sig in lots:
            open_exposure[sig] += qty * price
            open_shares[sig] += qty

    rows = []
    for sig, b in realized.items():
        rt = int(b["round_trips"])
        win_rate = (b["wins"] / rt) if rt > 0 else 0.0
        metrics = _tearsheet_metrics(returns_by_sig.get(sig, []), pnls_by_sig.get(sig, []))
        rows.append({
            "signal": sig,
            "realized_pnl": round(b["realized_pnl"], 6),
            "round_trips": rt,
            "win_rate": round(win_rate, 4),
            **metrics,
            "buy_notional": round(b["buy_notional"], 4),
            "sell_notional": round(b["sell_notional"], 4),
            "open_notional": round(open_exposure.get(sig, 0.0), 4),
            "open_shares": round(open_shares.get(sig, 0.0), 6),
        })
    rows.sort(key=lambda r: r["realized_pnl"], reverse=True)
    total_realized = round(sum(r["realized_pnl"] for r in rows), 6)
    return {
        "by_signal": rows,
        "total_realized_pnl": total_realized,
        "trade_count": len(trades),
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
