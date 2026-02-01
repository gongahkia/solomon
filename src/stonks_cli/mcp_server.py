"""
MCP Server for stonks-cli.

This exposes all stonks-cli functionality as MCP tools that can be used by
AI assistants and other MCP clients.

Usage:
    Run directly: python -m stonks_cli.mcp_server
    Or via uv: uv run python -m stonks_cli.mcp_server
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from stonks_cli.commands import (
    do_alert_add,
    do_alert_check,
    do_alert_list,
    do_alert_remove,
    do_analyze,
    do_backtest,
    do_config_show,
    do_config_validate,
    do_correlation,
    do_data_cache_info,
    do_data_fetch,
    do_data_verify,
    do_dividend_calendar,
    do_dividend_info,
    do_doctor,
    do_earnings,
    do_fundamentals,
    do_history_list,
    do_insider,
    do_movers,
    do_news,
    do_paper_buy,
    do_paper_leaderboard,
    do_paper_sell,
    do_paper_status,
    do_plugins_list,
    do_portfolio_add,
    do_portfolio_allocation,
    do_portfolio_history,
    do_portfolio_remove,
    do_portfolio_show,
    do_quick,
    do_report_latest,
    do_report_view,
    do_schedule_status,
    do_sector,
    do_signals_diff,
    do_version,
    do_watchlist_analyze,
    do_watchlist_list,
    do_watchlist_remove,
    do_watchlist_set,
)
from stonks_cli.config import load_config
from stonks_cli.data.providers import normalize_ticker
from stonks_cli.pipeline import provider_for_config


def _default_out_dir() -> Path:
    """Return the default output directory for reports."""
    return Path("reports")


# Initialize the MCP server
mcp = FastMCP(
    "stonks-cli",
    json_response=True,
)


def _serialize(obj: Any) -> Any:
    """Convert objects to JSON-serializable format."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    if isinstance(obj, (list, tuple)):
        return [_serialize(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    return obj


# =============================================================================
# Quick Analysis Tools
# =============================================================================


@mcp.tool()
def quick_analysis(tickers: list[str]) -> Any:
    """
    Get quick one-liner analysis for one or more stock tickers.
    Returns price, change percentage, action recommendation, and confidence.

    Args:
        tickers: List of ticker symbols (e.g., ["AAPL", "MSFT", "GOOG"])

    Returns:
        Dictionary with results for each ticker including price, change_pct,
        action (buy/sell/hold), and confidence score.
    """
    results = do_quick(tickers)
    return {"results": [_serialize(r) for r in results]}


@mcp.tool()
def get_version() -> Any:
    """Get the stonks-cli version information."""
    return {"version": do_version()}


@mcp.tool()
def run_doctor() -> Any:
    """
    Diagnose the stonks-cli environment.
    Checks configuration, data availability, and system health.
    """
    report = do_doctor()
    return _serialize(report)


# =============================================================================
# Market Data Tools
# =============================================================================


@mcp.tool()
def get_fundamentals(ticker: str) -> Any:
    """
    Get fundamental data for a stock ticker.
    Includes P/E ratio, market cap, revenue, earnings, and other key metrics.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
    """
    result = do_fundamentals(ticker, as_json=True)
    return _serialize(result) or {}


@mcp.tool()
def get_news(ticker: str, sentiment_only: bool = False) -> Any:
    """
    Get recent news headlines for a stock ticker.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        sentiment_only: If True, show only notable sentiment headlines
    """
    headlines = do_news(ticker, notable_only=sentiment_only)
    return {"headlines": _serialize(headlines)}


@mcp.tool()
def get_earnings(ticker: str | None = None, show_next: bool = False) -> Any:
    """
    Get earnings information for a ticker or upcoming earnings calendar.

    Args:
        ticker: Stock ticker symbol (optional, shows calendar if not provided)
        show_next: If True, show only the next upcoming earnings date
    """
    result = do_earnings(ticker=ticker, show_next=show_next)
    return _serialize(result)


@mcp.tool()
def get_insider_transactions(
    ticker: str,
    days: int = 90,
    buys_only: bool = False,
    sells_only: bool = False,
) -> Any:
    """
    Get recent insider transactions for a stock.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        days: Number of days to look back (default: 90)
        buys_only: Show only buy transactions
        sells_only: Show only sell transactions
    """
    transactions = do_insider(ticker, days=days, buys_only=buys_only, sells_only=sells_only)
    return {"transactions": _serialize(transactions)}


@mcp.tool()
def get_dividend_info(ticker: str) -> Any:
    """
    Get dividend information for a stock ticker.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
    """
    result = do_dividend_info(ticker)
    return _serialize(result)


@mcp.tool()
def get_dividend_calendar(days: int = 30) -> Any:
    """
    Scan watchlist tickers for upcoming ex-dividend dates.

    Args:
        days: Number of days to look ahead (default: 30)
    """
    events = do_dividend_calendar(days=days)
    return {"events": _serialize(events)}


@mcp.tool()
def get_sector_performance(sector_name: str) -> Any:
    """
    Get sector ETF performance compared to SPY.

    Args:
        sector_name: Sector name (e.g., "Technology", "Healthcare", "Financials")
    """
    result = do_sector(sector_name)
    return _serialize(result)


@mcp.tool()
def get_correlation_matrix(tickers: list[str], days: int = 252) -> Any:
    """
    Compute correlation matrix for given stock tickers.

    Args:
        tickers: List of ticker symbols (e.g., ["AAPL", "MSFT", "GOOG"])
        days: Number of trading days for correlation calculation (default: 252)
    """
    matrix = do_correlation(tickers, days=days)
    return {"matrix": _serialize(matrix)}


@mcp.tool()
def get_market_movers(sector: bool = False) -> Any:
    """
    Fetch daily performance of major indices or sector ETFs.

    Args:
        sector: If True, show sector ETFs instead of major indices
    """
    movers = do_movers(sector=sector)
    return {"movers": _serialize(movers)}


# =============================================================================
# Chart Tools (return chart data for visualization)
# =============================================================================


@mcp.tool()
def get_chart_data(
    ticker: str,
    days: int = 90,
    candle: bool = False,
    volume: bool = False,
    sma_periods: list[int] | None = None,
    show_bollinger: bool = False,
) -> Any:
    """
    Get price chart data for a stock ticker.
    Returns data suitable for visualization.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        days: Number of days to display (default: 90)
        candle: Include candlestick OHLC data
        volume: Include volume data
        sma_periods: List of SMA periods to include (e.g., [20, 50, 200])
        show_bollinger: Include Bollinger Bands data
    """
    cfg = load_config()
    normalized = normalize_ticker(ticker)
    provider = provider_for_config(cfg, normalized)
    series = provider.fetch_daily(normalized)

    df = series.df.tail(days).copy()
    if df.empty:
        return {"error": "No data found"}

    result: dict[str, Any] = {
        "ticker": normalized,
        "dates": df.index.strftime("%Y-%m-%d").tolist(),
        "close": df["close"].tolist(),
    }

    if candle and "open" in df.columns and "high" in df.columns and "low" in df.columns:
        result["open"] = df["open"].tolist()
        result["high"] = df["high"].tolist()
        result["low"] = df["low"].tolist()

    if volume and "volume" in df.columns:
        result["volume"] = df["volume"].tolist()

    return result


@mcp.tool()
def get_chart_compare_data(tickers: list[str], days: int = 90) -> Any:
    """
    Get comparison chart data for multiple tickers (normalized).

    Args:
        tickers: List of ticker symbols to compare
        days: Number of days to display (default: 90)
    """
    cfg = load_config()
    result: dict[str, Any] = {"dates": []}

    first = True
    for t in tickers:
        normalized = normalize_ticker(t)
        provider = provider_for_config(cfg, normalized)
        df = provider.fetch_daily(normalized).df.tail(days)

        if df.empty:
            continue

        if first:
            result["dates"] = df.index.strftime("%Y-%m-%d").tolist()
            first = False

        # Normalize to percentage change from start
        start_price = float(df["close"].iloc[0]) if not df.empty else 0
        if start_price:
            normalized_px = ((df["close"] - start_price) / start_price) * 100
            result[normalized] = normalized_px.tolist()

    return result


@mcp.tool()
def get_chart_rsi_data(ticker: str, period: int = 14, days: int = 90) -> Any:
    """
    Get RSI indicator chart data.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        period: RSI period (default: 14)
        days: Number of days to display (default: 90)
    """
    from stonks_cli.analysis.indicators import rsi

    cfg = load_config()
    normalized = normalize_ticker(ticker)
    provider = provider_for_config(cfg, normalized)
    df = provider.fetch_daily(normalized).df

    if df.empty:
        return {"error": "No data found"}

    rsi_series = rsi(df["close"], period)
    df_slice = df.tail(days)
    rsi_slice = rsi_series.tail(days)

    return {
        "ticker": normalized,
        "dates": df_slice.index.strftime("%Y-%m-%d").tolist(),
        "rsi": rsi_slice.fillna(0).tolist(),
    }


# =============================================================================
# Analysis Tools
# =============================================================================


@mcp.tool()
def run_analysis(
    tickers: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    benchmark: str | None = None,
) -> Any:
    """
    Run full technical analysis on tickers.

    Args:
        tickers: List of ticker symbols (uses config default if not provided)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        benchmark: Benchmark ticker for comparison (e.g., "SPY")
    """
    out_dir = _default_out_dir()
    report_path = do_analyze(
        tickers=tickers,
        out_dir=out_dir,
        start=start_date,
        end=end_date,
        benchmark=benchmark,
    )
    return {"report_path": str(report_path)}


@mcp.tool()
def run_backtest(
    tickers: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Any:
    """
    Run backtest simulation on tickers.

    Args:
        tickers: List of ticker symbols (uses config default if not provided)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    out_dir = _default_out_dir()
    report_path = do_backtest(
        tickers=tickers,
        start=start_date,
        end=end_date,
        out_dir=out_dir,
    )
    return {"backtest_path": str(report_path)}


@mcp.tool()
def get_signals_diff() -> Any:
    """
    Compare latest vs previous analysis run.
    Shows changes in signals/recommendations between runs.
    """
    diff = do_signals_diff()
    return _serialize(diff)


# =============================================================================
# Watchlist Tools
# =============================================================================


@mcp.tool()
def list_watchlists() -> Any:
    """List all configured watchlists with their tickers."""
    watchlists = do_watchlist_list()
    return {"watchlists": _serialize(watchlists)}


@mcp.tool()
def create_watchlist(name: str, tickers: list[str]) -> Any:
    """
    Create or update a watchlist.

    Args:
        name: Watchlist name
        tickers: List of ticker symbols to include
    """
    do_watchlist_set(name, tickers)
    return {"status": "success", "name": name, "tickers": tickers}


@mcp.tool()
def delete_watchlist(name: str) -> Any:
    """
    Delete a watchlist.

    Args:
        name: Watchlist name to delete
    """
    do_watchlist_remove(name)
    return {"status": "success", "deleted": name}


@mcp.tool()
def analyze_watchlist(
    name: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Any:
    """
    Run analysis on all tickers in a watchlist.

    Args:
        name: Watchlist name
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    out_dir = _default_out_dir()
    artifacts = do_watchlist_analyze(
        name,
        out_dir=out_dir,
        start=start_date,
        end=end_date,
    )
    return {
        "report_path": str(artifacts.report_path),
        "json_path": str(artifacts.json_path) if artifacts.json_path else None
    }


# =============================================================================
# Portfolio Tools
# =============================================================================


@mcp.tool()
def add_portfolio_position(
    ticker: str,
    shares: float,
    cost_basis: float,
    purchase_date: str | None = None,
    notes: str | None = None,
) -> Any:
    """
    Add a position to your portfolio.

    Args:
        ticker: Stock ticker symbol
        shares: Number of shares
        cost_basis: Cost per share
        purchase_date: Purchase date (optional, YYYY-MM-DD format)
        notes: Optional notes about the position
    """
    result = do_portfolio_add(
        ticker=ticker,
        shares=shares,
        cost_basis=cost_basis,
        purchase_date=purchase_date,
        notes=notes,
    )
    return _serialize(result)


@mcp.tool()
def remove_portfolio_position(ticker: str, shares: float, sale_price: float) -> Any:
    """
    Remove shares from a portfolio position.

    Args:
        ticker: Stock ticker symbol
        shares: Number of shares to remove
        sale_price: Sale price per share
    """
    do_portfolio_remove(ticker, shares, sale_price)
    return {"status": "success", "ticker": ticker, "shares_sold": shares}


@mcp.tool()
def get_portfolio() -> Any:
    """Get current portfolio positions with current prices and P&L."""
    result = do_portfolio_show(include_total=True)
    return _serialize(result)


@mcp.tool()
def get_portfolio_allocation() -> Any:
    """Get portfolio allocation percentages by position."""
    result = do_portfolio_allocation()
    return _serialize(result)


@mcp.tool()
def get_portfolio_history() -> Any:
    """Get portfolio transaction history."""
    result = do_portfolio_history()
    return {"transactions": _serialize(result)}


# =============================================================================
# Paper Trading Tools
# =============================================================================


@mcp.tool()
def paper_buy(ticker: str, shares: float) -> Any:
    """
    Execute a paper (simulated) buy order.

    Args:
        ticker: Stock ticker symbol
        shares: Number of shares to buy
    """
    result = do_paper_buy(ticker, shares)
    return _serialize(result)


@mcp.tool()
def paper_sell(ticker: str, shares: float) -> Any:
    """
    Execute a paper (simulated) sell order.

    Args:
        ticker: Stock ticker symbol
        shares: Number of shares to sell
    """
    result = do_paper_sell(ticker, shares)
    return _serialize(result)


@mcp.tool()
def get_paper_status() -> Any:
    """Get paper trading portfolio status with P&L summary."""
    result = do_paper_status()
    return _serialize(result)


@mcp.tool()
def get_paper_leaderboard() -> Any:
    """Get paper trading performance metrics for leaderboard."""
    result = do_paper_leaderboard()
    return _serialize(result)


# =============================================================================
# Alert Tools
# =============================================================================


@mcp.tool()
def create_alert(ticker: str, condition: str, threshold: float) -> Any:
    """
    Create a price alert for a stock.

    Args:
        ticker: Stock ticker symbol
        condition: Alert condition ("above", "below", "crosses_above", "crosses_below")
        threshold: Price threshold for the alert
    """
    result = do_alert_add(ticker, condition, threshold)
    return _serialize(result)


@mcp.tool()
def list_alerts() -> Any:
    """List all configured alerts."""
    alerts = do_alert_list()
    return {"alerts": _serialize(alerts)}


@mcp.tool()
def delete_alert(alert_id: str) -> Any:
    """
    Delete an alert by ID.

    Args:
        alert_id: The alert ID to delete
    """
    do_alert_remove(alert_id)
    return {"status": "success", "deleted": alert_id}


@mcp.tool()
def check_alerts() -> Any:
    """
    Check all alerts and return any that have been triggered.
    Sends notifications for triggered alerts.
    """
    triggered = do_alert_check()
    return {"triggered": _serialize(triggered)}


# =============================================================================
# Data Management Tools
# =============================================================================


@mcp.tool()
def fetch_data(tickers: list[str] | None = None) -> Any:
    """
    Fetch and cache market data for tickers.

    Args:
        tickers: List of ticker symbols (uses config default if not provided)
    """
    result = do_data_fetch(tickers)
    return _serialize(result)


@mcp.tool()
def verify_data(tickers: list[str] | None = None) -> Any:
    """
    Verify data health for tickers.
    Checks for gaps, staleness, and data quality issues.

    Args:
        tickers: List of ticker symbols (uses config default if not provided)
    """
    result = do_data_verify(tickers)
    return _serialize(result)


@mcp.tool()
def get_cache_info() -> Any:
    """Get information about the data cache (size, entries, etc)."""
    result = do_data_cache_info()
    return _serialize(result)


# =============================================================================
# Configuration Tools
# =============================================================================


@mcp.tool()
def get_config() -> Any:
    """Get current stonks-cli configuration."""
    config = do_config_show()
    return {"config": _serialize(config)}


@mcp.tool()
def validate_config() -> Any:
    """Validate the current configuration file."""
    result = do_config_validate()
    return _serialize(result)


# =============================================================================
# Report & History Tools
# =============================================================================


@mcp.tool()
def get_latest_report() -> Any:
    """Get the most recent analysis report."""
    result = do_report_latest(include_json=True)
    return _serialize(result)


@mcp.tool()
def view_report(path: str | None = None) -> Any:
    """
    View a specific report.

    Args:
        path: Path to report file (uses latest if not provided)
    """
    result = do_report_view(Path(path) if path else None)
    return _serialize(result)


@mcp.tool()
def list_history(limit: int = 20) -> Any:
    """
    List recent analysis history.

    Args:
        limit: Maximum number of history entries to return (default: 20)
    """
    result = do_history_list(limit=limit)
    return {"history": _serialize(result)}


# =============================================================================
# Schedule Tools
# =============================================================================


@mcp.tool()
def get_schedule_status() -> Any:
    """Get the current schedule status including next run time."""
    result = do_schedule_status()
    return _serialize(result)


# =============================================================================
# Plugin Tools
# =============================================================================


@mcp.tool()
def list_plugins() -> Any:
    """List all available plugins and their status."""
    result = do_plugins_list()
    return {"plugins": _serialize(result)}


# =============================================================================
# Entry Point
# =============================================================================


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
