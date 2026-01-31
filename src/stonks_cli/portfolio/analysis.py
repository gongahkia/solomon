from __future__ import annotations

from stonks_cli.portfolio.models import Portfolio


def calculate_portfolio_allocation(
    portfolio: Portfolio, prices: dict[str, float]
) -> dict[str, float]:
    """Compute percentage allocation per ticker.

    Args:
        portfolio: The portfolio to analyze.
        prices: Dict mapping ticker to current price.

    Returns:
        Dict mapping ticker to percentage of total portfolio value.
    """
    allocations: dict[str, float] = {}
    total_value = 0.0

    # Calculate market value for each position
    position_values: dict[str, float] = {}
    for pos in portfolio.positions:
        price = prices.get(pos.ticker, 0.0)
        market_value = pos.shares * price
        position_values[pos.ticker] = position_values.get(pos.ticker, 0.0) + market_value
        total_value += market_value

    # Include cash in total value
    total_value += portfolio.cash_balance

    if total_value == 0:
        return allocations

    # Calculate percentages
    for ticker, value in position_values.items():
        allocations[ticker] = (value / total_value) * 100

    # Add cash allocation if present
    if portfolio.cash_balance > 0:
        allocations["CASH"] = (portfolio.cash_balance / total_value) * 100

    return allocations
