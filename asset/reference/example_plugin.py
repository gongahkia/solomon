"""Example stonks-cli plugin.

Usage (config.json):

  {
    "plugins": ["asset/example_plugin.py"],
    "strategy": "example_sma20",
    "data": {
      "provider": "plugin",
      "plugin_name": "local_csv",
      "csv_path": "./prices.csv"
    }
  }

This demonstrates:
- A simple strategy function returning a Recommendation
- A provider factory returning an object with fetch_daily()

"""

from __future__ import annotations

from stonks_cli.analysis.strategy import Recommendation
from stonks_cli.data.providers import CsvProvider, normalize_ticker


def example_sma20_strategy(df):
    """Toy strategy: BUY_DCA if close > SMA20, else AVOID_OR_HEDGE."""
    if df is None or getattr(df, "empty", True):
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="No rows")
    if "close" not in df.columns:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="Missing close")

    close = df["close"]
    if len(close) < 25:
        return Recommendation(action="INSUFFICIENT_HISTORY", confidence=0.1, rationale="Need >= 25 rows")

    sma20 = close.rolling(20).mean().iloc[-1]
    last = float(close.iloc[-1])
    if last > float(sma20):
        return Recommendation(
            action="BUY_DCA",
            confidence=0.55,
            rationale=f"close {last:.2f} > SMA20 {float(sma20):.2f}",
        )
    return Recommendation(
        action="AVOID_OR_HEDGE",
        confidence=0.55,
        rationale=f"close {last:.2f} <= SMA20 {float(sma20):.2f}",
    )


def local_csv_provider_factory(cfg, ticker: str):
    """Provider factory that reads a local OHLCV CSV using the built-in CsvProvider."""
    t = normalize_ticker(ticker)
    override = (cfg.ticker_overrides or {}).get(t)
    data_cfg = override.data if override else cfg.data
    if not data_cfg.csv_path:
        raise ValueError("local_csv provider requires data.csv_path (or per-ticker override csv_path)")
    return CsvProvider(data_cfg.csv_path)


STONKS_STRATEGIES = {
    "example_sma20": example_sma20_strategy,
}

STONKS_PROVIDER_FACTORIES = {
    "local_csv": local_csv_provider_factory,
}
