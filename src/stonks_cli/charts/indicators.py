from __future__ import annotations

import pandas as pd
import plotext as plt

from stonks_cli.analysis.indicators import rsi


def plot_rsi(df: pd.DataFrame, ticker: str, period: int = 14, days: int = 90) -> None:
    """Plot RSI indicator chart with overbought/oversold zones.

    Args:
        df: DataFrame with DatetimeIndex and 'close' column
        ticker: Ticker symbol for the chart title
        period: RSI period (default 14)
        days: Number of days to display
    """
    if df.empty or "close" not in df.columns:
        print(f"No data available for {ticker}")
        return

    # Get the last N days
    data = df.tail(days)
    if data.empty:
        print(f"No data available for {ticker}")
        return

    # Calculate RSI
    rsi_values = rsi(data["close"], window=period)
    rsi_list = rsi_values.tolist()

    # Clear any previous plot
    plt.clear_figure()

    # Plot RSI line
    plt.plot(rsi_list, label=f"RSI({period})", color="cyan", marker="braille")

    # Plot overbought/oversold lines
    overbought = [70] * len(rsi_list)
    oversold = [30] * len(rsi_list)
    midline = [50] * len(rsi_list)

    plt.plot(overbought, label="Overbought (70)", color="red")
    plt.plot(oversold, label="Oversold (30)", color="green")
    plt.plot(midline, label="Midline (50)", color="yellow")

    plt.title(f"{ticker} - RSI({period}) Last {days} Days")
    plt.xlabel("Days")
    plt.ylabel("RSI")

    # Set y-axis limits
    plt.ylim(0, 100)

    plt.show()
