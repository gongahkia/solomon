from __future__ import annotations

import plotext as plt
import pandas as pd


def plot_comparison(tickers: list[str], dfs: dict[str, pd.DataFrame], days: int = 90) -> None:
    """Plot normalized percentage change comparison of multiple tickers.

    Args:
        tickers: List of ticker symbols
        dfs: Dict mapping ticker to DataFrame with 'close' column
        days: Number of days to display
    """
    if not tickers or not dfs:
        print("No data to compare")
        return

    # Clear any previous plot
    plt.clear_figure()

    # More visually distinct colors using RGB tuples for maximum contrast
    colors = [
        (255, 0, 0),      # Bright Red
        (0, 200, 0),      # Bright Green
        (0, 100, 255),    # Bright Blue
        (255, 200, 0),    # Yellow/Gold
        (0, 255, 255),    # Cyan
        (255, 0, 255),    # Magenta
        (255, 128, 0),    # Orange
        (150, 150, 255),  # Light Purple
        (255, 100, 150),  # Pink
        (0, 255, 150),    # Mint Green
    ]
    
    # Different markers for each ticker
    markers = ["braille", "dot", "hd", "fhd", "braille", "dot", "hd", "fhd"]

    for i, ticker in enumerate(tickers):
        df = dfs.get(ticker)
        if df is None or df.empty or "close" not in df.columns:
            print(f"Skipping {ticker}: no data")
            continue

        # Get the last N days
        data = df.tail(days)
        if data.empty or len(data) < 2:
            print(f"Skipping {ticker}: insufficient data")
            continue

        # Normalize to percentage change from first day
        prices = data["close"].tolist()
        base_price = prices[0]
        if base_price == 0:
            continue

        pct_changes = [(p / base_price - 1) * 100 for p in prices]

        color = colors[i % len(colors)]
        marker = markers[i % len(markers)]
        plt.plot(pct_changes, label=ticker, color=color, marker=marker)

    plt.title(f"Performance Comparison - Last {days} Days")
    plt.xlabel("Days")
    plt.ylabel("Change (%)")
    
    # Enable color mode for better color support
    plt.colorless(False)

    plt.show()
