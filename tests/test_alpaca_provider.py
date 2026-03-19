from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from datetime import datetime

import pandas as pd


# --- mock Alpaca SDK objects ---
@dataclass
class _MockBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class _MockBarsResponse:
    def __init__(self, data: dict):
        self.data = data


class _MockClient:
    def __init__(self, api_key, secret_key):
        self.bars_to_return: _MockBarsResponse | None = None

    def get_stock_bars(self, request):
        return self.bars_to_return

    def get_stock_latest_quote(self, request):
        return {}


class _MockStockBarsRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _MockStockLatestQuoteRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _MockTimeFrame:
    Day = "Day"


def _install_fake_alpaca():
    """inject fake alpaca modules into sys.modules so AlpacaProvider can import them."""
    stock_mod = types.ModuleType("alpaca.data.historical.stock")
    stock_mod.StockHistoricalDataClient = _MockClient
    req_mod = types.ModuleType("alpaca.data.requests")
    req_mod.StockBarsRequest = _MockStockBarsRequest
    req_mod.StockLatestQuoteRequest = _MockStockLatestQuoteRequest
    tf_mod = types.ModuleType("alpaca.data.timeframe")
    tf_mod.TimeFrame = _MockTimeFrame
    alpaca_pkg = types.ModuleType("alpaca")
    alpaca_data = types.ModuleType("alpaca.data")
    alpaca_hist = types.ModuleType("alpaca.data.historical")
    sys.modules["alpaca"] = alpaca_pkg
    sys.modules["alpaca.data"] = alpaca_data
    sys.modules["alpaca.data.historical"] = alpaca_hist
    sys.modules["alpaca.data.historical.stock"] = stock_mod
    sys.modules["alpaca.data.requests"] = req_mod
    sys.modules["alpaca.data.timeframe"] = tf_mod


_install_fake_alpaca()

from stonks_cli.data.alpaca import AlpacaProvider  # noqa: E402


def test_fetch_daily_returns_price_series_with_correct_columns():
    provider = AlpacaProvider()
    client = provider._get_client()
    bars = [
        _MockBar(datetime(2025, 1, 3), 10.0, 11.0, 9.0, 10.5, 100),
        _MockBar(datetime(2025, 1, 2), 9.0, 10.0, 8.0, 9.5, 200),
    ]
    client.bars_to_return = _MockBarsResponse({"AAPL": bars})
    series = provider.fetch_daily("aapl")
    assert series.ticker == "AAPL.US"  # normalize_ticker applied
    df = series.df
    assert isinstance(df.index, pd.DatetimeIndex)
    assert list(df.index) == sorted(df.index)  # sorted
    for col in ("open", "high", "low", "close", "volume"):
        assert col in df.columns
    assert float(df.loc[pd.Timestamp("2025-01-02"), "close"]) == 9.5


def test_empty_response_returns_empty_dataframe():
    provider = AlpacaProvider()
    client = provider._get_client()
    client.bars_to_return = _MockBarsResponse({})
    series = provider.fetch_daily("MSFT")
    assert series.ticker == "MSFT.US"
    assert series.df.empty


def test_normalize_ticker_applied():
    provider = AlpacaProvider()
    client = provider._get_client()
    client.bars_to_return = _MockBarsResponse({})
    series = provider.fetch_daily("goog")
    assert series.ticker == "GOOG.US"
