from __future__ import annotations

import importlib
import os
from datetime import datetime

import pandas as pd

from stonks_cli.data.providers import PriceProvider, PriceSeries, normalize_ticker


class AlpacaProvider(PriceProvider):
    def __init__(self, cfg=None):
        api_key = None
        secret_key = None
        paper = True
        if cfg is not None:
            ak = getattr(cfg, "api_keys", None)
            if ak is not None:
                api_key = getattr(ak, "alpaca_api_key", None)
                secret_key = getattr(ak, "alpaca_secret_key", None)
                paper = getattr(ak, "alpaca_paper", True)
        self._api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self._secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        self._paper = paper
        self._client = None # lazy-init

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            mod = importlib.import_module("alpaca.data.historical.stock")
        except Exception as e:
            raise ImportError("Alpaca provider requires alpaca-py: pip install alpaca-py") from e
        ClientCls = mod.StockHistoricalDataClient
        self._client = ClientCls(self._api_key, self._secret_key)
        return self._client

    def fetch_daily(self, ticker: str) -> PriceSeries:
        normalized = normalize_ticker(ticker)
        base_ticker = normalized.split(".")[0] # strip exchange suffix
        try:
            req_mod = importlib.import_module("alpaca.data.requests")
            tf_mod = importlib.import_module("alpaca.data.timeframe")
        except Exception as e:
            raise ImportError("Alpaca provider requires alpaca-py: pip install alpaca-py") from e
        StockBarsRequest = req_mod.StockBarsRequest
        TimeFrame = tf_mod.TimeFrame
        client = self._get_client()
        request = StockBarsRequest(
            symbol_or_symbols=base_ticker,
            timeframe=TimeFrame.Day,
            start=datetime(2000, 1, 1),
        )
        bars = client.get_stock_bars(request)
        if bars is None or not hasattr(bars, "data") or not bars.data:
            return PriceSeries(ticker=normalized, df=pd.DataFrame())
        bar_list = bars.data.get(base_ticker, [])
        if not bar_list:
            return PriceSeries(ticker=normalized, df=pd.DataFrame())
        rows = []
        for b in bar_list:
            rows.append({
                "date": pd.to_datetime(b.timestamp),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": int(b.volume),
            })
        df = pd.DataFrame(rows).set_index("date").sort_index()
        return PriceSeries(ticker=normalized, df=df)

    def fetch_latest_quote(self, ticker: str) -> dict:
        normalized = normalize_ticker(ticker)
        base_ticker = normalized.split(".")[0]
        try:
            req_mod = importlib.import_module("alpaca.data.requests")
        except Exception as e:
            raise ImportError("Alpaca provider requires alpaca-py: pip install alpaca-py") from e
        StockLatestQuoteRequest = req_mod.StockLatestQuoteRequest
        client = self._get_client()
        request = StockLatestQuoteRequest(symbol_or_symbols=base_ticker)
        resp = client.get_stock_latest_quote(request)
        if resp is None or base_ticker not in resp:
            return {}
        q = resp[base_ticker]
        return {
            "ask_price": getattr(q, "ask_price", None),
            "ask_size": getattr(q, "ask_size", None),
            "bid_price": getattr(q, "bid_price", None),
            "bid_size": getattr(q, "bid_size", None),
            "timestamp": getattr(q, "timestamp", None),
        }
