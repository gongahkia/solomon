from __future__ import annotations

import pandas as pd
import plotext as plt

from stonks_cli.analysis.indicators import bollinger_bands, sma


def plot_price_history(
    df: pd.DataFrame,
    ticker: str,
    days: int = 90,
    sma_periods: list[int] | None = None,
    show_bb: bool = False,
) -> None:
    """Plot a line chart of closing prices to the terminal.

    Args:
        df: DataFrame with DatetimeIndex and 'close' column
        ticker: Ticker symbol for the chart title
        days: Number of days to display
        sma_periods: List of SMA periods to overlay (e.g., [20, 50, 200])
        show_bb: Whether to show Bollinger Bands
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

    # Plot price
    plt.plot(prices, label="Price", color="white", marker="braille")

    # Plot SMA overlays
    sma_colors = ["green", "yellow", "red", "cyan", "magenta"]
    if sma_periods:
        close_series = data["close"]
        for i, period in enumerate(sma_periods):
            sma_values = sma(close_series, period)
            sma_list = sma_values.tolist()
            color = sma_colors[i % len(sma_colors)]
            plt.plot(sma_list, label=f"SMA{period}", color=color)

    # Plot Bollinger Bands
    if show_bb:
        close_series = data["close"]
        lower, mid, upper = bollinger_bands(close_series, window=20, num_std=2.0)
        plt.plot(lower.tolist(), label="BB Lower", color="blue")
        plt.plot(mid.tolist(), label="BB Mid", color="cyan")
        plt.plot(upper.tolist(), label="BB Upper", color="blue")

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
