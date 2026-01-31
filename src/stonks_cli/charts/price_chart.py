from __future__ import annotations

import plotext as plt
import pandas as pd


def plot_price_history(df: pd.DataFrame, ticker: str, days: int = 90) -> None:
    """Plot a line chart of closing prices to the terminal.

    Args:
        df: DataFrame with DatetimeIndex and 'close' column
        ticker: Ticker symbol for the chart title
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

    # Extract dates and prices
    dates = [str(d.date()) if hasattr(d, "date") else str(d) for d in data.index]
    prices = data["close"].tolist()

    # Clear any previous plot
    plt.clear_figure()

    # Configure the plot
    plt.plot(prices, marker="braille")
    plt.title(f"{ticker} - Last {len(prices)} Days")
    plt.xlabel("Days")
    plt.ylabel("Price ($)")

    # Set x-axis ticks (show a few date labels)
    if len(dates) > 10:
        step = len(dates) // 5
        tick_positions = list(range(0, len(dates), step))
        tick_labels = [dates[i] for i in tick_positions]
        plt.xticks(tick_positions, tick_labels)

    plt.show()


def plot_with_volume(df: pd.DataFrame, ticker: str, days: int = 60) -> None:
    """Plot a two-panel chart with price on top and volume on bottom.

    Args:
        df: DataFrame with DatetimeIndex, 'close' and 'volume' columns
        ticker: Ticker symbol for the chart title
        days: Number of days to display
    """
    if df.empty or "close" not in df.columns:
        print(f"No data available for {ticker}")
        return

    has_volume = "volume" in df.columns

    # Get the last N days
    data = df.tail(days)
    if data.empty:
        print(f"No data available for {ticker}")
        return

    # Extract data
    prices = data["close"].tolist()
    volumes = data["volume"].tolist() if has_volume else None

    # Clear any previous plot
    plt.clear_figure()

    if has_volume and volumes:
        # Create subplots: 2 rows, 1 column
        plt.subplots(2, 1)

        # Top panel: Price chart (takes more space)
        plt.subplot(1, 1)
        plt.plot(prices, marker="braille")
        plt.title(f"{ticker} - Price")
        plt.ylabel("Price ($)")

        # Bottom panel: Volume bars
        plt.subplot(2, 1)
        plt.bar(list(range(len(volumes))), volumes, color="blue")
        plt.title("Volume")
        plt.xlabel("Days")
        plt.ylabel("Volume")
    else:
        # No volume data, just show price
        plt.plot(prices, marker="braille")
        plt.title(f"{ticker} - Last {len(prices)} Days (no volume data)")
        plt.xlabel("Days")
        plt.ylabel("Price ($)")

    plt.show()
