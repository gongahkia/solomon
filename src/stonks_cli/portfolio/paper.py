from __future__ import annotations

import json
from pathlib import Path
import platformdirs
from stonks_cli.portfolio.models import Portfolio

def get_paper_portfolio_path() -> Path:
    """Get platform-appropriate path to paper_portfolio.json."""
    data_dir = Path(platformdirs.user_data_dir("stonks-cli"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "paper_portfolio.json"

def save_paper_portfolio(portfolio: Portfolio) -> None:
    """Save paper portfolio to disk."""
    path = get_paper_portfolio_path()
    path.write_text(json.dumps(portfolio.to_dict(), indent=2), encoding="utf-8")

from datetime import date, datetime

def load_paper_portfolio() -> Portfolio:
    """Load paper portfolio from disk."""
    path = get_paper_portfolio_path()
    if not path.exists():
         raise FileNotFoundError("Paper portfolio not initialized. Run 'stonks paper init' first.")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Portfolio.from_dict(data)
    except Exception:
         raise ValueError("Invalid paper portfolio file.")

def get_paper_history_path() -> Path:
    data_dir = Path(platformdirs.user_data_dir("stonks-cli"))
    return data_dir / "paper_history.jsonl"

def log_paper_transaction(action: str, ticker: str, shares: float, price: float, gain_loss: float = None) -> None:
    path = get_paper_history_path()
    entry = {
         "timestamp": datetime.now().isoformat(),
         "action": action,
         "ticker": ticker,
         "shares": shares,
         "price": price,
    }
    if gain_loss is not None:
         entry["gain_loss"] = gain_loss

    with open(path, "a", encoding="utf-8") as f:
         f.write(json.dumps(entry) + "\n")

def paper_buy(ticker: str, shares: float, price: float) -> dict:
    """Buy shares for paper portfolio."""
    from stonks_cli.portfolio.models import Position

    portfolio = load_paper_portfolio()

    cost = shares * price
    if portfolio.cash_balance < cost:
        raise ValueError(f"Insufficient cash. Required: ${cost:.2f}, Available: ${portfolio.cash_balance:.2f}")

    portfolio.cash_balance -= cost

    position = Position(
        ticker=ticker.upper(),
        shares=shares,
        cost_basis_per_share=price,
        purchase_date=date.today(),
        notes="Paper Trade"
    )
    portfolio.positions.append(position)
    save_paper_portfolio(portfolio)

    log_paper_transaction("BUY", ticker.upper(), shares, price)

    return {
        "ticker": ticker.upper(),
        "shares": shares,
        "price": price,
        "total_cost": cost,
        "cash_remaining": portfolio.cash_balance
    }

def paper_sell(ticker: str, shares: float, price: float) -> dict:
    """Sell shares from paper portfolio."""
    portfolio = load_paper_portfolio()
    ticker_upper = ticker.upper()

    positions = [p for p in portfolio.positions if p.ticker == ticker_upper]
    positions.sort(key=lambda p: p.purchase_date)

    total_avail = sum(p.shares for p in positions)
    if total_avail < shares:
         raise ValueError(f"Insufficient shares. Have {total_avail}, trying to sell {shares}")

    remaining = shares
    total_cost_basis = 0.0
    to_remove = []

    for pos in positions:
        if remaining <= 0:
            break
        if pos.shares <= remaining:
             total_cost_basis += pos.shares * pos.cost_basis_per_share
             remaining -= pos.shares
             to_remove.append(pos)
        else:
             total_cost_basis += remaining * pos.cost_basis_per_share
             pos.shares -= remaining
             remaining = 0

    for pos in to_remove:
        portfolio.positions.remove(pos)

    proceeds = shares * price
    portfolio.cash_balance += proceeds

    realized_gl = proceeds - total_cost_basis
    gl_pct = (realized_gl / total_cost_basis * 100) if total_cost_basis > 0 else 0.0

    save_paper_portfolio(portfolio)
    log_paper_transaction("SELL", ticker_upper, shares, price, gain_loss=realized_gl)

    return {
        "ticker": ticker_upper,
        "shares": shares,
        "price": price,
        "proceeds": proceeds,
        "gain_loss": realized_gl,
        "gain_loss_pct": gl_pct,
        "cash_remaining": portfolio.cash_balance
    }

def init_paper_portfolio(starting_cash: float = 10000.0) -> Portfolio:
    """Initialize a new paper trading portfolio."""
    portfolio = Portfolio(cash_balance=starting_cash, positions=[])
    save_paper_portfolio(portfolio)

    # Clear history
    path_hist = get_paper_history_path()
    path_hist.write_text("", encoding="utf-8")

    log_paper_transaction("INIT", "CASH", starting_cash, 1.0)

    return portfolio


def calculate_paper_performance(
    portfolio: Portfolio,
    initial_cash: float,
    current_prices: dict[str, float] | None = None,
) -> dict:
    """Calculate performance metrics."""
    path = get_paper_history_path()
    trades = []
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if rec.get("action") == "SELL" and rec.get("gain_loss") is not None:
                        trades.append(rec)
                except Exception:
                    pass

    # Metrics
    num_trades = len(trades)
    winning_trades = [t for t in trades if t["gain_loss"] > 0]
    win_rate = (len(winning_trades) / num_trades * 100) if num_trades > 0 else 0.0

    best_trade = max(trades, key=lambda t: t["gain_loss"]) if trades else None
    worst_trade = min(trades, key=lambda t: t["gain_loss"]) if trades else None

    # Sharpe & Max Drawdown (Approximate based on closed trades)
    sharpe_ratio = 0.0
    max_drawdown = 0.0
    
    if trades:
        import statistics
        
        # Sharpe (Trade-based)
        pct_returns = []
        for t in trades:
            proceeds = t["shares"] * t["price"]
            gain = t["gain_loss"]
            cost = proceeds - gain
            if cost > 0:
                pct_returns.append(gain / cost)
        
        if len(pct_returns) > 1:
            avg_ret = statistics.mean(pct_returns)
            std_dev = statistics.stdev(pct_returns)
            # Simple Sharpe: Avg / StdDev (not annualized)
            sharpe_ratio = (avg_ret / std_dev) if std_dev > 0 else 0.0
        elif len(pct_returns) == 1:
            sharpe_ratio = pct_returns[0] # Not really defined, but return value

        # Max Drawdown (Realized Equity)
        equity = initial_cash
        peak = equity
        
        # Sort trades by timestamp to be sure (though usually appended)
        trades_sorted = sorted(trades, key=lambda x: x["timestamp"])
        
        for t in trades_sorted:
            equity += t["gain_loss"]
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

    total_value = portfolio.cash_balance
    if current_prices:
        for p in portfolio.positions:
            total_value += p.shares * current_prices.get(p.ticker, p.cost_basis_per_share)
    else:
        for p in portfolio.positions:
            total_value += p.shares * p.cost_basis_per_share

    total_return_pct = (
        ((total_value - initial_cash) / initial_cash * 100) if initial_cash > 0 else 0.0
    )

    return {
        "total_value": total_value,
        "total_return_pct": total_return_pct,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "win_rate": win_rate,
        "num_trades": num_trades,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown,
    }
