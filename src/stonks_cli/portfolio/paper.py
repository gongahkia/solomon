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

def init_paper_portfolio(starting_cash: float = 10000.0) -> Portfolio:
    """Initialize a new paper trading portfolio."""
    portfolio = Portfolio(cash_balance=starting_cash, positions=[])
    save_paper_portfolio(portfolio)
    return portfolio
