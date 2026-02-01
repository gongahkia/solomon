from __future__ import annotations

import pandas as pd


def compute_correlation_matrix(tickers: list[str], dfs: dict[str, pd.DataFrame], days: int = 252) -> pd.DataFrame:
    """Compute pairwise Pearson correlation matrix of daily returns.

    Args:
        tickers: List of ticker symbols.
        dfs: Dict mapping ticker to DataFrame with 'Close' column.
        days: Number of trading days to use for calculation.

    Returns:
        DataFrame with correlation matrix (tickers as both index and columns).
    """
    returns_data = {}
    for ticker in tickers:
        if ticker not in dfs:
            continue
        df = dfs[ticker]
        if "Close" not in df.columns:
            continue
        close = df["Close"].tail(days + 1)
        daily_returns = close.pct_change().dropna()
        returns_data[ticker] = daily_returns

    if not returns_data:
        return pd.DataFrame()

    returns_df = pd.DataFrame(returns_data)
    return returns_df.corr(method="pearson")


def compute_beta(ticker_df: pd.DataFrame, benchmark_df: pd.DataFrame, days: int = 252) -> float:
    """Compute beta coefficient of ticker returns vs benchmark.

    Args:
        ticker_df: DataFrame with 'Close' column for the ticker.
        benchmark_df: DataFrame with 'Close' column for the benchmark.
        days: Number of trading days to use for calculation.

    Returns:
        Beta coefficient (float). Returns NaN if insufficient data.
    """
    if "Close" not in ticker_df.columns or "Close" not in benchmark_df.columns:
        return float("nan")

    ticker_close = ticker_df["Close"].tail(days + 1)
    benchmark_close = benchmark_df["Close"].tail(days + 1)

    ticker_returns = ticker_close.pct_change().dropna()
    benchmark_returns = benchmark_close.pct_change().dropna()

    # Align the series by index
    aligned = pd.DataFrame({"ticker": ticker_returns, "benchmark": benchmark_returns}).dropna()

    if len(aligned) < 2:
        return float("nan")

    covariance = aligned["ticker"].cov(aligned["benchmark"])
    variance = aligned["benchmark"].var()

    if variance == 0:
        return float("nan")

    return covariance / variance
