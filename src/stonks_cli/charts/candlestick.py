from __future__ import annotations

import pandas as pd
import plotext as plt


def plot_candlestick(df: pd.DataFrame, ticker: str, days: int = 60) -> None:
    """Plot a candlestick chart of OHLC data to the terminal.

    Args:
        df: DataFrame with DatetimeIndex and 'open', 'high', 'low', 'close' columns
        ticker: Ticker symbol for the chart title
        days: Number of days to display
    """
    required_cols = {"open", "high", "low", "close"}
    if df.empty or not required_cols.issubset(set(df.columns)):
        missing = required_cols - set(df.columns)
        print(f"No OHLC data available for {ticker} (missing: {missing})")
        return

    # Get the last N days
    data = df.tail(days)
    if data.empty:
        print(f"No data available for {ticker}")
        return

    # Extract OHLC data
    dates = list(range(len(data)))
    opens = data["open"].tolist()
    highs = data["high"].tolist()
    lows = data["low"].tolist()
    closes = data["close"].tolist()

    # Clear any previous plot
    plt.clear_figure()

    # Plot candlestick chart
    plt.candlestick(dates, {"Open": opens, "Close": closes, "High": highs, "Low": lows})
    plt.title(f"{ticker} - Candlestick ({len(data)} Days)")
    plt.xlabel("Days")
    plt.ylabel("Price ($)")

    plt.show()
