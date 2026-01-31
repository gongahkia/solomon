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

def init_paper_portfolio(starting_cash: float = 10000.0) -> Portfolio:
    """Initialize a new paper trading portfolio."""
    portfolio = Portfolio(cash_balance=starting_cash, positions=[])
    save_paper_portfolio(portfolio)
    return portfolio
