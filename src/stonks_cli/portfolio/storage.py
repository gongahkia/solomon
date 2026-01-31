from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import platformdirs

from stonks_cli.portfolio.models import Portfolio, Position


def get_portfolio_path() -> Path:
    """Get platform-appropriate path to portfolio.json."""
    data_dir = Path(platformdirs.user_data_dir("stonks-cli"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "portfolio.json"


def get_history_path() -> Path:
    """Get platform-appropriate path to portfolio_history.jsonl."""
    data_dir = Path(platformdirs.user_data_dir("stonks-cli"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "portfolio_history.jsonl"


def load_portfolio() -> Portfolio:
    """Load portfolio from disk, returning empty Portfolio if file doesn't exist."""
    path = get_portfolio_path()
    if not path.exists():
        return Portfolio()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Portfolio.from_dict(data)
    except Exception:
        return Portfolio()


def save_portfolio(portfolio: Portfolio) -> None:
    """Save portfolio to disk with updated timestamp."""
    portfolio.updated_at = datetime.now()
    path = get_portfolio_path()
    path.write_text(json.dumps(portfolio.to_dict(), indent=2), encoding="utf-8")


def add_position(
    ticker: str,
    shares: float,
    cost_basis: float,
    purchase_date: date | None = None,
    notes: str | None = None,
) -> Position:
    """Add a new position to the portfolio and save."""
    portfolio = load_portfolio()

    position = Position(
        ticker=ticker.upper(),
        shares=shares,
        cost_basis_per_share=cost_basis,
        purchase_date=purchase_date or date.today(),
        notes=notes,
    )

    portfolio.positions.append(position)
    save_portfolio(portfolio)

    # Log the transaction
    log_transaction("add", ticker, shares, cost_basis)

    return position


def remove_position(ticker: str, shares: float, sale_price: float) -> dict:
    """Remove shares from a position using FIFO cost basis.

    Returns dict with realized_gain_loss calculated from cost basis.
    """
    portfolio = load_portfolio()
    ticker_upper = ticker.upper()

    # Find positions for this ticker (FIFO order by purchase date)
    ticker_positions = [p for p in portfolio.positions if p.ticker == ticker_upper]
    ticker_positions.sort(key=lambda p: p.purchase_date)

    if not ticker_positions:
        raise ValueError(f"No position found for {ticker_upper}")

    total_shares_available = sum(p.shares for p in ticker_positions)
    if total_shares_available < shares:
        raise ValueError(f"Insufficient shares. Have {total_shares_available}, trying to sell {shares}")

    # Calculate realized gain/loss using FIFO
    remaining_to_sell = shares
    total_cost_basis = 0.0
    positions_to_remove = []

    for pos in ticker_positions:
        if remaining_to_sell <= 0:
            break

        if pos.shares <= remaining_to_sell:
            # Sell entire position
            total_cost_basis += pos.shares * pos.cost_basis_per_share
            remaining_to_sell -= pos.shares
            positions_to_remove.append(pos)
        else:
            # Partial sell
            total_cost_basis += remaining_to_sell * pos.cost_basis_per_share
            pos.shares -= remaining_to_sell
            remaining_to_sell = 0

    # Remove fully sold positions
    for pos in positions_to_remove:
        portfolio.positions.remove(pos)

    proceeds = shares * sale_price
    realized_gain_loss = proceeds - total_cost_basis
    gain_loss_pct = (realized_gain_loss / total_cost_basis * 100) if total_cost_basis > 0 else 0.0

    save_portfolio(portfolio)

    # Log the transaction
    log_transaction("remove", ticker, shares, sale_price, gain_loss=realized_gain_loss)

    return {
        "ticker": ticker_upper,
        "shares_sold": shares,
        "sale_price": sale_price,
        "proceeds": proceeds,
        "cost_basis": total_cost_basis,
        "realized_gain_loss": realized_gain_loss,
        "gain_loss_pct": gain_loss_pct,
    }


def log_transaction(
    action: str,
    ticker: str,
    shares: float,
    price: float,
    gain_loss: float | None = None,
) -> None:
    """Append a transaction to portfolio_history.jsonl."""
    path = get_history_path()

    entry = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "ticker": ticker.upper(),
        "shares": shares,
        "price": price,
    }
    if gain_loss is not None:
        entry["gain_loss"] = gain_loss

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
